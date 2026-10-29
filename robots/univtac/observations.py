# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Explicit sensor/proprioception allowlist; evaluator state stays separate."""

from __future__ import annotations

import time

import numpy as np

from ._panda.transforms import compose


def array(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value).copy()


def sensor_observation(
    native, robot_state, references, *, control_step, physics_step, calibration=None
):
    """Copy known measurements only, dropping actors, atom tags and other truth."""
    cameras = {}
    for name in ("head", "wrist"):
        source = native.get("observation", {}).get(name, {})
        cameras[name] = {
            key: array(source[key]) for key in ("rgb", "depth") if key in source
        }
        if "rgb" in cameras[name]:
            cameras[name]["image_size"] = list(cameras[name]["rgb"].shape[:2])
        if "depth" in cameras[name]:
            cameras[name]["depth_image_size"] = list(cameras[name]["depth"].shape[:2])
            cameras[name]["depth_units"] = "m"
        cameras[name]["image_origin"] = "top_left"
        cameras[name]["image_axes"] = "x_right_y_down"
        if calibration and name in calibration:
            cameras[name]["calibration"] = calibration[name]
    tactile = {}
    for side in ("left", "right"):
        source = native.get("tactile", {}).get(f"{side}_tactile", {})
        data = {key: array(source[key]) for key in ("rgb", "depth") if key in source}
        if side in references:
            data["reference_rgb"] = array(references[side])
        data["reference_kind"] = "episode_initial_contact"
        data["tracking_quality"] = None
        data["marker_units"] = "pixels"
        data["marker_coordinate_order"] = "x,y"
        data["marker_origin"] = "top_left"
        data["marker_axes"] = "x_right_y_down"
        if "rgb" in data:
            data["image_size"] = list(data["rgb"].shape[:2])
        if "depth" in data:
            data["depth_image_size"] = list(data["depth"].shape[:2])
            data["depth_units"] = "mm"
            data["depth_semantics"] = "native_sensor_camera_depth_not_indentation"
        if "marker" in source:
            marker = array(source["marker"])
            if marker.ndim != 3 or marker.shape[0] != 2 or marker.shape[-1] != 2:
                raise ValueError("Expected native marker shape (2, N, 2)")
            data["marker_reference"] = marker[0]
            data["marker_current"] = marker[1]
            data["marker_displacement"] = marker[1] - marker[0]
        tactile[side] = data
    root, hand = robot_state["root_pose_w"], robot_state["hand_pose"]
    position, quaternion = compose(
        root["position"],
        root["quaternion_wxyz"],
        hand["position"],
        hand["quaternion_wxyz"],
    )
    return {
        "cameras": cameras,
        "tactile": tactile,
        "state": {
            "eef_pose_wxyz": np.r_[position, quaternion],
            "gripper": float(robot_state["gripper_qpos"]) / 0.039,
            "joint_positions": np.asarray(robot_state["qpos"][:7]),
            "pose_frame": "world",
            "eef_frame": "panda_hand",
            "position_units": "m",
            "gripper_units": "normalized_0_1",
        },
        "timestamp": time.time(),
        "control_step": int(control_step),
        "physics_step": int(physics_step),
        "physics_dt": 1 / 120,
        "simulation_time_s": int(physics_step) / 120,
    }
