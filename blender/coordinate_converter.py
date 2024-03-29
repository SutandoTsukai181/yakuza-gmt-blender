from math import atan, tan
from typing import Dict, List, Tuple

from bpy.types import Camera
from mathutils import Matrix, Quaternion, Vector

from ..gmt_lib import *
from ..gmt_lib.gmt.structure.cmt import CMTAnimation
from .bone_props import GMTBlenderBoneProps


def pos_to_blender(pos):
    return Vector([-pos[0], pos[2], pos[1]])


def pos_from_blender(pos: Vector) -> Tuple[float]:
    return (-pos[0], pos[2], pos[1])


def rot_to_blender(rot):
    return Quaternion([rot[3], -rot[0], rot[2], rot[1]])


def rot_from_blender(rot: Quaternion) -> Tuple[float]:
    return (-rot[1], rot[3], rot[2], rot[0])


def pattern1_to_blender(pattern: List[List[int]]) -> List[int]:
    return list(map(lambda x: (x[0],), pattern))


def pattern1_from_blender(pattern: List[int]) -> List[List[int]]:
    return [pattern, pattern[1:] + [pattern[-1]]]


def pattern2_to_blender(pattern: List[int]) -> List[int]:
    # No need to change anything for now
    return pattern


def pattern2_from_blender(pattern: List[int]) -> List[List[int]]:
    return pattern


def fov_to_blender(fov, sensor_height):
    # sensor_height should be 100.0 here
    return (sensor_height / 2) / tan(fov / 2)


def fov_from_blender(fov, sensor_height):
    # sensor_height should be 100.0 here
    return 2 * atan(sensor_height / (2 * fov))


def focus_point_to_blender(focus_point, location):
    return location + ((focus_point - location).to_track_quat('Z', 'Y') @ Vector((0.0, 0.0, -(focus_point - location).length)))


def focus_point_from_blender(focus_point, location):
    return location + ((focus_point - location).to_track_quat('-Z', 'Y') @ Vector((0.0, 0.0, (focus_point - location).length)))


def convert_gmt_curve_to_blender(curve: GMTCurve):
    curve.fill_channels()

    if curve.type == GMTCurveType.LOCATION:
        for kf in curve.keyframes:
            kf.value = pos_to_blender(kf.value)
    elif curve.type == GMTCurveType.ROTATION:
        for kf in curve.keyframes:
            kf.value = rot_to_blender(kf.value)


def convert_cmt_anm_to_blender(anm: CMTAnimation, camera_data: Camera):
    for frame in anm.frames:
        frame.location = pos_to_blender(frame.location)
        frame.focus_point = focus_point_to_blender(pos_to_blender(frame.focus_point), frame.location)
        frame.fov = fov_to_blender(frame.fov, camera_data.sensor_height)


def convert_cmt_anm_from_blender(anm: CMTAnimation, camera_data: Camera):
    for frame in anm.frames:
        frame.location = Vector(pos_from_blender(frame.location))
        frame.focus_point = focus_point_from_blender(Vector(pos_from_blender(frame.focus_point)), frame.location)
        frame.fov = fov_from_blender(frame.fov, camera_data.sensor_height)


def transform_location_to_blender(bone_props: Dict[str, GMTBlenderBoneProps], bone_name: str, values: List[Vector]):
    prop = bone_props.get(bone_name, GMTBlenderBoneProps())
    head = prop.head

    parent_head = bone_props.get(prop.parent_name)
    if parent_head:
        parent_head = parent_head.head
    else:
        parent_head = Vector()

    loc = prop.loc
    rot = prop.rot

    pre_mat = (
        Matrix.Translation(loc).inverted()
        @ rot.to_matrix().to_4x4().inverted()
    )

    post_mat = (
        rot.to_matrix().to_4x4()
        @ Matrix.Translation(loc)
    )

    values = list(map(lambda x: (pre_mat @ Matrix.Translation(x - head + parent_head) @ post_mat).to_translation(), values))

    return values


def transform_rotation_to_blender(bone_props: Dict[str, GMTBlenderBoneProps], bone_name: str, values: List[Quaternion]):
    prop = bone_props.get(bone_name, GMTBlenderBoneProps())

    parent_rot = bone_props.get(prop.parent_name)
    if parent_rot:
        parent_rot = parent_rot.rot_local
    else:
        parent_rot = Quaternion()

    rot = prop.rot
    rot_local = prop.rot_local

    pre_quat = rot.inverted() @ parent_rot
    post_quat = rot_local.inverted() @ parent_rot.inverted() @ rot

    return list(map(lambda x: pre_quat @ x @ post_quat, values))


def transform_location_from_blender(bone_props: Dict[str, GMTBlenderBoneProps], bone_name: str, values: List[Vector]) -> List[Tuple[float]]:
    prop = bone_props.get(bone_name, GMTBlenderBoneProps())
    head = prop.head

    parent_head = bone_props.get(prop.parent_name)
    if parent_head:
        parent_head = parent_head.head
    else:
        parent_head = Vector()

    loc = prop.loc
    rot = prop.rot

    pre_mat = (
        rot.to_matrix().to_4x4()
        @ Matrix.Translation(loc)
    )

    post_mat = (
        Matrix.Translation(loc).inverted()
        @ rot.to_matrix().to_4x4().inverted()
    )

    values = list(map(lambda x: pos_from_blender((
        pre_mat
        @ Matrix.Translation(x)
        @ post_mat
    ).to_translation() + head - parent_head), values))

    return values


def transform_rotation_from_blender(bone_props: Dict[str, GMTBlenderBoneProps], bone_name: str, values: List[Quaternion]) -> List[Tuple[float]]:
    prop = bone_props.get(bone_name, GMTBlenderBoneProps())

    parent_rot = bone_props.get(prop.parent_name)
    if parent_rot:
        parent_rot = parent_rot.rot_local
    else:
        parent_rot = Quaternion()

    rot = prop.rot
    rot_local = prop.rot_local

    pre_quat = parent_rot.inverted() @ rot
    post_quat = rot.inverted() @ parent_rot @ rot_local

    return list(map(lambda x: rot_from_blender(pre_quat @ x @ post_quat), values))
