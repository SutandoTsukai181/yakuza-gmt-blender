from copy import deepcopy
from typing import Dict

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Armature, FCurve, Operator
from bpy_extras.io_utils import ExportHelper
from mathutils import Matrix, Quaternion, Vector

from ..read_cmt import *
from ..structure.file import *
from ..structure.version import GMTProperties
from ..write import write_file
from . import bone_props
from .bone_props import GMTBlenderBoneProps, get_bones_props
from .coordinate_converter import (pattern_from_blender, pos_from_blender,
                                   rot_from_blender)
from .error import GMTError


class ExportGMT(Operator, ExportHelper):
    """Exports an animation to the GMT format"""
    bl_idname = "export_scene.gmt"
    bl_label = "Export Yakuza GMT"

    filter_glob: StringProperty(default="*.gmt", options={"HIDDEN"})

    filename_ext = '.gmt'

    def anm_callback(self, context):
        items = []

        anm_name = ""
        ao = bpy.context.active_object
        if ao and ao.animation_data:
            # add the selected action first so that it's the default value
            selected_anm = ao.animation_data.action
            if selected_anm:
                anm_name = selected_anm.name
                items = [(anm_name, anm_name, "")]

        for a in [act for act in bpy.data.actions if act.name != anm_name]:
            items.append((a.name, a.name, ""))
        return items

    def skeleton_callback(self, context):
        items = []
        for a in bpy.data.armatures:
            items.append((a.name, a.name, ""))
        return items

    def anm_update(self, context):
        name = self.anm_name
        if "(" in name and ")" in name:
            # used to avoid suffixes (e.g ".001")
            self.gmt_file_name = name[name.index("(")+1:name.index(")")]
            self.gmt_anm_name = name[:name.index("(")]

    anm_name: EnumProperty(
        items=anm_callback,
        name="Action",
        description="The action to be exported",
        update=anm_update)

    skeleton_name: EnumProperty(
        items=skeleton_callback,
        name="Skeleton",
        description="The armature used for the action")

    gmt_properties: EnumProperty(
        items=[('KENZAN', 'Ryu Ga Gotoku Kenzan', ""),
               ('YAKUZA_3', 'Yakuza 3, 4, Dead Souls', ""),
               ('YAKUZA_5', 'Yakuza 5', ""),
               ('YAKUZA_0', 'Yakuza 0, Kiwami, Ishin, FOTNS', ""),
               ('YAKUZA_6', 'Yakuza 6, 7, Kiwami 2, Judgment', "")],
        name="Game Preset",
        description="Target game which the exported GMT will be used in",
        default=3)

    gmt_file_name: StringProperty(
        name="GMT File Name",
        description="Internal GMT file name",
        maxlen=30)

    gmt_anm_name: StringProperty(
        name="GMT Animation Name",
        description="Internal GMT animation name",
        maxlen=30)

    def draw(self, context):
        layout = self.layout

        layout.use_property_split = True
        layout.use_property_decorate = True  # No animation.

        layout.prop(self, 'anm_name')
        layout.prop(self, 'skeleton_name')
        layout.prop(self, 'gmt_properties')
        layout.prop(self, 'gmt_file_name')
        layout.prop(self, 'gmt_anm_name')

        # update file and anm name if both are empty
        if self.gmt_file_name == self.gmt_anm_name == "":
            self.anm_update(context)

    def execute(self, context):
        arm = self.check_armature()
        if arm is str:
            self.report({"ERROR"}, arm)
            return {'CANCELLED'}

        try:
            exporter = GMTExporter(
                self.filepath, self.as_keywords(ignore=("filter_glob",)))
            exporter.export()

            self.report({"INFO"}, f"Finished exporting {exporter.anm_name}")
            return {'FINISHED'}
        except GMTError as error:
            print("Catching Error")
            self.report({"ERROR"}, str(error))
        return {'CANCELLED'}

    def check_armature(self):
        # check the active object first
        ao = bpy.context.active_object
        if ao and ao.type == 'ARMATURE' and ao.data.bones[:]:
            return 0

        # if the active object isn't a valid armature, get its collection and check

        if ao:
            collection = ao.users_collection[0]
        else:
            collection = bpy.context.view_layer.active_layer_collection

        meshObjects = [o for o in bpy.data.collections[collection.name].objects
                       if o.data in bpy.data.meshes[:] and o.find_armature()]

        armatures = [a.find_armature() for a in meshObjects]
        if meshObjects:
            armature = armatures[0]
            if armature.data.bones[:]:
                bpy.context.view_layer.objects.active = armature
                return 0

        return "No armature found to get animation from"


class GMTExporter:
    def __init__(self, filepath, export_settings: Dict):
        self.filepath = filepath
        # used for bone translation before exporting
        self.anm_name = export_settings.get("anm_name")
        self.gmt_file_name = export_settings.get("gmt_file_name")
        self.gmt_anm_name = export_settings.get("gmt_anm_name")
        self.skeleton_name = export_settings.get("skeleton_name")
        self.start_frame = export_settings.get("start_frame")  # convenience
        self.end_frame = export_settings.get("end_frame")  # convenience
        self.interpolation = export_settings.get(
            "interpolation")  # manual interpolation if needed
        self.gmt_properties = GMTProperties(
            export_settings.get("gmt_properties"))
        # auth or motion, for converting center/vector pos
        self.gmt_context = export_settings.get("gmt_context")

        self.gmt_file = GMTFile()

    armature: Armature
    bone_props: Dict[str, GMTBlenderBoneProps]

    def export(self):
        print(f"Exporting animation: {self.anm_name}")

        self.get_anm()
        self.format_header()
        with open(self.filepath, 'wb') as f:
            f.write(write_file(self.gmt_file, self.gmt_properties.version))

        print("GMT Export finished")

    def format_header(self):
        header = GMTHeader()

        header.big_endian = True
        header.version = self.gmt_properties.version
        header.file_name = Name(self.gmt_file_name)
        header.flags = 0

        self.gmt_file.header = header

    def get_anm(self):
        self.armature = bpy.data.armatures.get(self.skeleton_name)

        if not self.armature:
            raise GMTError("Armature not found")

        action = bpy.data.actions.get(self.anm_name)

        anm = Animation()
        anm.name = Name(self.gmt_anm_name)
        anm.frame_rate = 30.0
        anm.index = anm.index1 = anm.index2 = anm.index3 = 0

        anm.bones = []

        self.setup_bone_locs()

        for group in action.groups.values():
            if group.name != "vector_c_n":
                anm.bones.append(self.make_bone(group.name, group.channels))
            else:
                center, c_index = find_bone("center_c_n", anm.bones)

                if not len(center.curves):
                    center_channels = [
                        c for c in group.channels if "gmt_" in c.data_path]

                    # Use vector head (0) because we already added center head once
                    center = self.make_bone(group.name, center_channels)
                    center.name = Name("center_c_n")

                    if c_index != -1:
                        anm.bones[c_index] = center
                    else:
                        anm.bones.insert(0, center)

                vector = self.make_bone(
                    group.name, [c for c in group.channels if "gmt_" not in c.data_path])
                anm.bones.append(vector)

                if self.gmt_properties.is_dragon_engine:
                    if not len(center.curves):
                        center.curves = [new_pos_curve(), new_rot_curve()]
                else:
                    vector_curves = deepcopy(vector.curves)
                    for c in vector.curves:
                        c = c.to_horizontal()

                    vertical = new_pos_curve()
                    if len(center.position_curves()):
                        vertical = center.position_curves()[0].to_vertical()

                    center.curves = vector_curves
                    for c in center.curves:
                        if 'POS' in c.curve_format.name:
                            c = add_curve(c, vertical)

                    # TODO: Move this to the converter once it's implemented
                    # Add scale bone to mark this gmt as non DE
                    scale = Bone()
                    scale.name = Name("scale")
                    scale.curves = [new_pos_curve(), new_rot_curve()]
                    anm.bones.insert(0, scale)

        self.gmt_file.animations = [anm]

    def make_bone(self, bone_name: str, channels: List[FCurve]) -> Bone:
        bone = Bone()
        bone.name = Name(bone_name)
        bone.curves = []

        loc_len, rot_len = 0, 0
        loc_curves, rot_curves, pat1_curves = dict(), dict(), dict()

        for c in channels:
            if "location" in c.data_path[c.data_path.rindex(".") + 1:]:
                if loc_len == 0:
                    loc_len = len(c.keyframe_points)
                elif loc_len != len(c.keyframe_points):
                    raise GMTError(
                        f"FCurve {c.data_path} has channels with unmatching keyframes")

                if c.array_index == 0:
                    loc_curves["x"] = c
                elif c.array_index == 1:
                    loc_curves["y"] = c
                elif c.array_index == 2:
                    loc_curves["z"] = c
            elif "rotation_quaternion" in c.data_path[c.data_path.rindex(".") + 1:]:
                if rot_len == 0:
                    rot_len = len(c.keyframe_points)
                elif rot_len != len(c.keyframe_points):
                    raise GMTError(
                        f"FCurve {c.data_path} has channels with unmatching keyframes")

                if c.array_index == 0:
                    rot_curves["w"] = c
                elif c.array_index == 1:
                    rot_curves["x"] = c
                elif c.array_index == 2:
                    rot_curves["y"] = c
                elif c.array_index == 3:
                    rot_curves["z"] = c
            elif "pat1" in c.data_path:
                if c.data_path[c.data_path.rindex(".") + 1:] == "pat1_left_hand":
                    pat1_curves["left_" + str(c.array_index)] = c
                elif c.data_path[c.data_path.rindex(".") + 1:] == "pat1_right_hand":
                    pat1_curves["right_" + str(c.array_index)] = c

        if len(loc_curves) == 3:
            bone.curves.append(self.make_curve(
                loc_curves,
                axes=["x", "y", "z"],
                curve_format=CurveFormat.POS_VEC3,
                group_name=bone_name))

        if len(rot_curves) == 4:
            format = CurveFormat.ROT_QUAT_SCALED \
                if self.gmt_properties.version > 0x10001 \
                else CurveFormat.ROT_QUAT_HALF_FLOAT
            bone.curves.append(self.make_curve(
                rot_curves,
                axes=["w", "x", "y", "z"],
                curve_format=format,
                group_name=bone_name))

        for pat in pat1_curves:
            format = CurveFormat.PAT1_LEFT_HAND \
                if "left" in pat \
                else CurveFormat.PAT1_RIGHT_HAND
            bone.curves.append(self.make_curve(
                pat1_curves,
                axes=[pat],
                curve_format=format,
                group_name=bone_name))

        return bone

    def make_curve(self, fcurves: List[FCurve], axes: List[str], curve_format: CurveFormat, group_name: str) -> Curve:
        curve = Curve()
        curve.graph = Graph()

        axes_co = []
        for axis in axes:
            axis_co = [0] * 2 * len(fcurves[axis].keyframe_points)
            fcurves[axis].keyframe_points.foreach_get("co", axis_co)
            axes_co.append(axis_co)

        curve.curve_format = curve_format

        curve.graph.keyframes = [int(x) for x in axes_co[0][::2]]
        curve.graph.delimiter = -1

        interpolate = True
        if len(axes_co) == 3:
            # Position vector
            curve.values = list(map(
                lambda x, y, z: Vector((x, y, z)),
                axes_co[0][1:][::2],
                axes_co[1][1:][::2],
                axes_co[2][1:][::2]))
            curve.values = self.transform_location(group_name, curve.values)
        elif len(axes_co) == 4:
            # Rotation quaternion
            curve.values = list(map(
                lambda w, x, y, z: Quaternion((w, x, y, z)),
                axes_co[0][1:][::2],
                axes_co[1][1:][::2],
                axes_co[2][1:][::2],
                axes_co[3][1:][::2]))
            curve.values = self.transform_rotation(group_name, curve.values)
        elif len(axes_co) == 1:
            # Pat1
            axes_co = axes_co[0][1:][::2]
            if not self.gmt_properties.is_dragon_engine:
                # prevent pattern numbers larger than old engine max to be exported
                axes_co = self.correct_pattern(axes_co)
            axes_co = pattern_from_blender(axes_co)
            curve.values = list(map(
                lambda s, e: [int(s), int(e)],
                axes_co[0],
                axes_co[1]))
            interpolate = False

        if interpolate:
            # Apply constant interpolation by duplicating keyframes
            pol = [True] * len(fcurves[axes[0]].keyframe_points)
            axis_pol = pol.copy()
            for axis in axes:
                fcurves[axis].keyframe_points.foreach_get(
                    "interpolation", axis_pol)
                pol = list(map(lambda a, b: a and (b == 0),
                               pol, axis_pol))  # 'CONSTANT' = 0

            j = 0
            for i in range(len(pol) - 1):
                k = i + j
                if pol[i] and curve.graph.keyframes[k + 1] - curve.graph.keyframes[k] > 1:
                    curve.values.insert(k + 1, curve.values[k])
                    curve.graph.keyframes.insert(
                        k + 1, curve.graph.keyframes[k + 1] - 1)
                    j += 1

        return curve

    def setup_bone_locs(self):
        mode = bpy.context.mode
        bpy.ops.object.mode_set(mode='EDIT')
        
        self.bone_props = get_bones_props(self.armature.edit_bones)
        
        bpy.ops.object.mode_set(mode=mode)


    def correct_pattern(self, pattern):
        return list(map(lambda x: 0 if x > 17 else x, pattern))


    def transform_location(self, bone_name: str, values: List[Vector]):
        prop = self.bone_props[bone_name]
        head = prop.head
        parent_head = self.bone_props.get(prop.parent_name)
        if parent_head:
            parent_head = parent_head.head
        else:
            parent_head = Vector()

        loc = prop.loc
        rot = prop.rot
        
        values = list(map(lambda x: pos_from_blender((
            rot.to_matrix().to_4x4()
            @ Matrix.Translation(x)
        ).to_translation() + head - parent_head), values))
        
        print(values[0])
        print()

        return values


    def transform_rotation(self, bone_name: str, values: List[Quaternion]):
        prop = self.bone_props[bone_name]

        loc = prop.loc
        rot = prop.rot
        rot_local = prop.rot_local

        values = list(map(lambda x: rot_from_blender((
            rot_local.to_matrix().to_4x4()
            @ rot.to_matrix().to_4x4()
            @ x.to_matrix().to_4x4()
            @ rot.to_matrix().to_4x4().inverted()
        ).to_quaternion()), values))

        return values


def menu_func_export(self, context):
    self.layout.operator(ExportGMT.bl_idname, text='Yakuza Animation (.gmt)')
