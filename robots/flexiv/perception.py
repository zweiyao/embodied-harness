# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Read-only calibrated RGBD geometry from the collector's camera owner."""

import hashlib
import json
from pathlib import Path

import numpy as np


def _matrix(value):
    matrix = np.asarray(value, dtype=float)
    if (
        matrix.shape != (4, 4)
        or not np.isfinite(matrix).all()
        or not np.allclose(matrix[3], [0, 0, 0, 1])
        or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-6)
        or not np.isclose(np.linalg.det(matrix[:3, :3]), 1, atol=1e-6)
    ):
        raise ValueError("Invalid rigid calibration transform")
    return matrix


def _rotation(quaternion):
    q = np.asarray(quaternion, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all() or abs(np.linalg.norm(q) - 1) > 1e-3:
        raise ValueError("Expected a finite unit quaternion in wxyz order")
    w, x, y, z = q / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


class Calibration:
    """Frozen files plus validation of each actual collector snapshot."""

    def __init__(
        self,
        calibration_file,
        tool_tcp_file,
        *,
        allow_inconsistent_readonly=False,
        allow_provisional_side_control=False,
        operator_confirmed_calibration_sha256=None,
    ):
        paths = [Path(calibration_file).expanduser(), Path(tool_tcp_file).expanduser()]
        raw = [p.read_bytes() for p in paths]
        self.data, self.tool = [json.loads(value) for value in raw]
        self.hashes = {
            str(p): hashlib.sha256(value).hexdigest() for p, value in zip(paths, raw)
        }
        self.operator_confirmed_cameras = []
        if operator_confirmed_calibration_sha256 is not None:
            if not allow_provisional_side_control:
                raise ValueError(
                    "Operator confirmation requires supervised side control"
                )
            if operator_confirmed_calibration_sha256 != self.hashes[str(paths[0])]:
                raise ValueError(
                    "Operator confirmation does not match calibration SHA256"
                )
            self.operator_confirmed_cameras = ["side", "wrist"]
        for name in ("T_tcp_wrist_camera", "T_base_side_camera", "T_base_board"):
            _matrix(self.data[name])
        consistent = (
            self.data["wrist_consistency_passed"]
            and self.data["side_consistency_passed"]
        )
        self.provisional = not consistent
        self.provisional_readonly = (
            not consistent and not allow_provisional_side_control
        )
        self.side_control = allow_provisional_side_control
        if allow_provisional_side_control and not self.data["side_consistency_passed"]:
            raise ValueError("Side camera consistency must pass before side control")
        if not consistent and not (
            allow_inconsistent_readonly or allow_provisional_side_control
        ):
            raise ValueError("Calibration consistency checks did not pass")
        if self.tool["native_tool"] != self.data["tool"]:
            raise ValueError("Calibration and compensation use different native tools")
        self.offset = np.asarray(self.tool["tcp_to_grasp_translation_m"], dtype=float)
        if (
            self.offset.shape != (3,)
            or not np.isfinite(self.offset).all()
            or np.linalg.norm(self.offset) > 0.02
            or self.tool["coordinate_frame"] != "native_tool_tcp"
            or self.tool["rotation_offset"] != "identity"
        ):
            raise ValueError("Invalid native-TCP grasp compensation")

    def observation(self, snapshot):
        """Validate stationary PNG capture; retain geometry with its source images."""
        if snapshot["tool"] != self.data["tool"]:
            raise ValueError("Native tool changed; calibration is not applicable")
        poses = []
        for key in ("state_before", "state_after"):
            state = snapshot[key]
            if (
                state["robot_sn"] != self.data["robot_sn"]
                or state["coordinate_frame"] != "robot_base"
                or state["quaternion_order"] != "wxyz"
                or state["fault"]
            ):
                raise ValueError("Snapshot robot identity, frame or fault check failed")
            pose = np.asarray(state["tcp_pose"], dtype=float)
            velocity = np.asarray(state["joint_velocity"], dtype=float)
            if (
                pose.shape != (7,)
                or not np.isfinite(pose).all()
                or velocity.shape != (7,)
                or not np.isfinite(velocity).all()
                or np.max(np.abs(velocity)) > 0.005
            ):
                raise ValueError("Snapshot requires finite stationary robot state")
            transform = np.eye(4)
            transform[:3, :3] = _rotation(pose[3:])
            transform[:3, 3] = pose[:3]
            poses.append(transform)
        angle = np.arccos(
            np.clip((np.trace(poses[0][:3, :3].T @ poses[1][:3, :3]) - 1) / 2, -1, 1)
        )
        if np.linalg.norm(
            poses[0][:3, 3] - poses[1][:3, 3]
        ) > 0.0002 or angle > np.deg2rad(0.1):
            raise ValueError("Robot moved during the calibrated capture")
        images, cameras, depths = {}, {}, {}
        for role in ("wrist", "side"):
            name = self.data["board"][role]
            camera = snapshot["cameras"][name]
            expected = self.data["camera_intrinsics"][role]
            if any(
                camera["intrinsics"].get(k) != v
                for k, v in expected.items()
                if k != "source"
            ):
                raise ValueError(
                    f"{role} camera profile changed; recalibration required"
                )
            if not 0 <= camera["frame_age_s"] <= 0.15:
                raise ValueError(f"{role} camera frame is stale")
            if (
                camera.get("timestamp_domain") != "timestamp_domain.global_time"
                or not 0 <= camera.get("color_depth_skew_s", float("inf")) <= 0.05
            ):
                raise ValueError(f"{role} color/depth timestamps are not synchronized")
            transform = (
                poses[1] @ np.asarray(self.data["T_tcp_wrist_camera"])
                if role == "wrist"
                else np.asarray(self.data["T_base_side_camera"])
            )
            images[role] = camera["png_base64"]
            depth = np.asarray(camera["depth_m"], dtype=np.float32)
            if (
                camera.get("aligned_to") != "color"
                or depth.shape != (expected["height"], expected["width"])
                or not np.isfinite(depth).all()
                or np.any(depth < 0)
            ):
                raise ValueError(
                    f"{role} requires finite nonnegative color-aligned depth in metres"
                )
            depths[role] = depth
            cameras[role] = {
                k: v for k, v in camera.items() if k not in ("png_base64", "depth_m")
            }
            cameras[role]["T_base_camera"] = transform.tolist()
        # A stationary arm is insufficient if the two camera frames are far apart.
        skew = abs(
            cameras["wrist"]["frame_monotonic"] - cameras["side"]["frame_monotonic"]
        )
        if not np.isfinite(skew) or skew > 0.15:
            raise ValueError("Camera pair receipt times differ by more than 150 ms")
        metadata = {
            "cameras": cameras,
            "captured_at": snapshot["captured_at"],
            "state": snapshot["state_after"],
            "tool": snapshot["tool"],
            "source_sha256": self.hashes,
            "tcp_to_grasp_translation_m": self.offset.tolist(),
            "grasp_reference_base_m": (
                poses[1][:3, 3] + poses[1][:3, :3] @ self.offset
            ).tolist(),
            "T_base_board": self.data["T_base_board"],
            "deployment_approved": self.data.get("deployment_approved", False),
            "calibration_validation": {
                "wrist_passed": self.data["wrist_consistency_passed"],
                "side_passed": self.data["side_consistency_passed"],
                "provisional_readonly": self.provisional_readonly,
                "provisional": self.provisional,
                "control_camera": "side" if self.side_control else None,
            },
            "synchronization": snapshot["synchronization"],
            "frame_skew_s": skew,
            "motion_enabled": False,
            "depth_available": True,
        }
        if self.operator_confirmed_cameras:
            metadata["calibration_validation"].update(
                operator_confirmed_cameras=self.operator_confirmed_cameras,
                operator_confirmation={
                    "basis": "operator_reported_current_calibration_tested_in_task_area",
                    "calibration_sha256": next(iter(self.hashes.values())),
                    "measured_error_mm": None,
                },
                control_camera=None,
            )
        return {
            "state": snapshot["state_after"],
            "images_png": images,
            "camera_calibration": metadata,
            "missing_cameras": [],
            "depths": depths,
            "motion_enabled": False,
            "native_success": None,
        }


def _ray(pixel, box, camera):
    """Deproject RGB using its actual distortion model; never treat RGB as depth."""
    xy, bounds = np.asarray(pixel, dtype=float), np.asarray(box, dtype=float)
    intr = camera["intrinsics"]
    if (
        xy.shape != (2,)
        or bounds.shape != (4,)
        or not np.isfinite(xy).all()
        or not np.isfinite(bounds).all()
    ):
        raise ValueError("Use finite pixel [x,y] and whole-target box [x0,y0,x1,y1]")
    x0, y0, x1, y1 = bounds
    if (
        x0 < 3
        or y0 < 3
        or x1 > intr["width"] - 4
        or y1 > intr["height"] - 4
        or x0 >= x1
        or y0 >= y1
    ):
        raise ValueError(
            "Target box is clipped/at image border or invalid; do not localize"
        )
    if not (x0 <= xy[0] <= x1 and y0 <= xy[1] <= y1):
        raise ValueError("Matched point must lie inside its target box")
    # The factory inverse-Brown model is not OpenCV's forward distortion model.
    # SDK deprojection is pure pixel math and does not open a camera.
    import pyrealsense2 as rs

    models = {
        "distortion.none": rs.distortion.none,
        "distortion.inverse_brown_conrady": rs.distortion.inverse_brown_conrady,
        "distortion.brown_conrady": rs.distortion.brown_conrady,
    }
    if intr["model"] not in models:
        raise ValueError("Unsupported camera distortion model")
    spec = rs.intrinsics()
    spec.width, spec.height = intr["width"], intr["height"]
    spec.fx, spec.fy, spec.ppx, spec.ppy = (
        intr["fx"],
        intr["fy"],
        intr["ppx"],
        intr["ppy"],
    )
    spec.model, spec.coeffs = models[intr["model"]], intr["coeffs"]
    transform = _matrix(camera["T_base_camera"])
    ray = transform[:3, :3] @ np.asarray(
        rs.rs2_deproject_pixel_to_point(spec, xy.tolist(), 1.0)
    )
    return transform[:3, 3], ray / np.linalg.norm(ray)


def back_project(metadata, depth, camera, pixel, box):
    """Estimate a visible surface point from measured depth; never command motion."""
    if camera not in ("wrist", "side"):
        raise ValueError("Choose wrist or side")
    info = metadata["cameras"][camera]
    origin, direction = _ray(pixel, box, info)
    depth = np.asarray(depth)
    intr = info["intrinsics"]
    if depth.shape != (intr["height"], intr["width"]):
        raise ValueError("Depth image dimensions do not match calibration")
    x, y = [int(round(v)) for v in pixel]
    patch = depth[y - 2 : y + 3, x - 2 : x + 3]
    valid = patch[np.isfinite(patch) & (patch >= 0.05) & (patch <= 3.0)]
    if not np.isfinite(depth[y, x]) or not 0.05 <= depth[y, x] <= 3 or len(valid) < 13:
        raise ValueError("Selected pixel has invalid or insufficient measured depth")
    spread = float(np.percentile(valid, 90) - np.percentile(valid, 10))
    if spread > 0.02:
        raise ValueError(
            "Depth discontinuity exceeds 20 mm; select an interior surface pixel"
        )
    z = float(np.median(valid))
    camera_direction = np.asarray(info["T_base_camera"])[:3, :3].T @ direction
    point = origin + direction * (z / camera_direction[2])
    rotation = _rotation(metadata["state"]["tcp_pose"][3:])
    native_target = point - rotation @ np.asarray(
        metadata["tcp_to_grasp_translation_m"]
    )
    return {
        "point_base_m": point.tolist(),
        "coordinate_frame": "robot_base",
        "depth_m": z,
        "depth_patch_spread_m": spread,
        "valid_patch_pixels": len(valid),
        "source": "color_aligned_realsense_depth",
        "camera": camera,
        "captured_at": metadata["captured_at"],
        "native_tcp_if_this_point_is_grasp_reference_m": native_target.tolist(),
        "orientation_assumption": "unchanged from the recorded native TCP",
        "object_identity_verified": False,
        "motion_authorized": False,
        "calibration_validation": metadata["calibration_validation"],
        "note": "Valid depth is not independent accuracy or proof of object identification. "
        "The selected surface feature is not automatically a grasp center. "
        "This estimate is diagnostic only; no motion/workspace/collision approval.",
    }
