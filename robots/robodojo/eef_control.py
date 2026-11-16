# Adapted from GPT-as-Policy's robot-only kinematics, commit 8f3d362b077d.
# Copyright (c) 2026 Yu-Mool Shu and Lipxin Zheng.
# MIT license: see LICENSES/GPT-as-Policy-MIT.txt.
"""Robot-only FK and bounded local DLS for short dual-X5 EEF actions."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation


class EefTargetLimitError(ValueError):
    """A target is outside the permitted distance from the measured EEF."""


def transform(position: Any, quaternion_wxyz: Any) -> np.ndarray:
    """Convert a finite position and unit wxyz quaternion to a transform."""
    position = np.asarray(position, dtype=np.float64)
    quaternion = np.asarray(quaternion_wxyz, dtype=np.float64)
    if (
        position.shape != (3,)
        or quaternion.shape != (4,)
        or not np.isfinite(position).all()
        or not np.isfinite(quaternion).all()
        or abs(np.linalg.norm(quaternion) - 1) > 1e-4
    ):
        raise ValueError("Finite position and unit wxyz quaternion required")
    result = np.eye(4)
    result[:3, 3] = position
    result[:3, :3] = Rotation.from_quat(quaternion[[1, 2, 3, 0]]).as_matrix()
    return result


def pose_errors(
    current: np.ndarray, target: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return environment-frame translation and axis-angle errors."""
    return (
        target[:3, 3] - current[:3, 3],
        Rotation.from_matrix(target[:3, :3] @ current[:3, :3].T).as_rotvec(),
    )


def bounded(vector: np.ndarray, cap: float) -> np.ndarray:
    """Bound a vector's norm without changing its direction."""
    return vector * min(1.0, cap / max(float(np.linalg.norm(vector)), 1e-12))


def validate_targets(target: dict, state: dict, steps: int) -> dict:
    """Validate both arms and decision limits before any motion is executed."""
    if type(steps) is not int or not 1 <= steps <= 5:
        raise ValueError("steps must be an integer from 1 to 5")
    if set(target) != {"left", "right"}:
        raise ValueError("Explicit left/right targets required")
    result = {}
    for arm in ("left", "right"):
        value = target[arm]
        if set(value) != {"position", "quaternion_wxyz", "gripper_closed"}:
            raise ValueError(
                "Each arm requires position, quaternion_wxyz, gripper_closed"
            )
        if type(value["gripper_closed"]) is not bool:
            raise ValueError("Explicit boolean gripper_closed required")
        goal = transform(value["position"], value["quaternion_wxyz"])
        measured = np.asarray(state[f"{arm}_ee_pose"], dtype=np.float64)
        current = transform(measured[:3], measured[3:])
        translation, rotation = pose_errors(current, goal)
        if (
            np.linalg.norm(translation) > 0.05 + 1e-9
            or np.linalg.norm(rotation) > 0.35 + 1e-9
        ):
            raise EefTargetLimitError(
                f"{arm} target exceeds 0.05 m / 0.35 rad decision limit"
            )
        result[arm] = {key: value[key] for key in value}
    return result


class ArmFK:
    """Evaluate an arm's URDF chain without scene or object state."""

    def __init__(self, urdf: str, joint_names: list[str], base: str, tip: str):
        self.names = list(joint_names)
        edges = {
            joint.find("child").get("link"): joint
            for joint in ET.parse(urdf).getroot().findall("joint")
        }
        self.chain = []
        while tip != base:
            joint = edges[tip]
            origin = joint.find("origin")
            xyz = (
                np.fromstring(origin.get("xyz", "0 0 0"), sep=" ")
                if origin is not None
                else np.zeros(3)
            )
            rpy = (
                np.fromstring(origin.get("rpy", "0 0 0"), sep=" ")
                if origin is not None
                else np.zeros(3)
            )
            matrix = np.eye(4)
            matrix[:3, :3] = Rotation.from_euler("xyz", rpy).as_matrix()
            matrix[:3, 3] = xyz
            axis = joint.find("axis")
            axis = (
                np.fromstring(axis.get("xyz"), sep=" ")
                if axis is not None
                else np.array([1.0, 0, 0])
            )
            self.chain.insert(0, (joint.get("name"), joint.get("type"), matrix, axis))
            tip = joint.find("parent").get("link")
        moving = [name for name, kind, _, _ in self.chain if kind != "fixed"]
        if set(moving) != set(self.names):
            raise ValueError(f"URDF chain/arm joint mismatch: {moving}, {self.names}")

    def matrix(self, joints: Any) -> np.ndarray:
        """Return link6 relative to the configured robot base."""
        joints = np.asarray(joints, dtype=np.float64)
        if joints.shape != (len(self.names),) or not np.isfinite(joints).all():
            raise ValueError("Invalid arm joint vector")
        values, result = dict(zip(self.names, joints)), np.eye(4)
        for name, kind, origin, axis in self.chain:
            motion = np.eye(4)
            if kind in ("revolute", "continuous"):
                motion[:3, :3] = Rotation.from_rotvec(axis * values[name]).as_matrix()
            elif kind != "fixed":
                raise ValueError("Only fixed/revolute arm chain supported")
            result = result @ origin @ motion
        return result

    def bounded_target(
        self, joints: Any, limits: Any, root: np.ndarray, target: dict
    ) -> tuple[np.ndarray, dict]:
        """Compute one bounded DLS joint target from the current measured joints."""
        joints = np.asarray(joints, dtype=np.float64)
        current = root @ self.matrix(joints)
        goal = transform(target["position"], target["quaternion_wxyz"])
        translation, rotation = pose_errors(current, goal)
        error = np.r_[bounded(translation, 0.02), bounded(rotation, 0.1)]
        jacobian = np.zeros((6, len(joints)))
        for index in range(len(joints)):
            shifted = joints.copy()
            shifted[index] += 1e-5
            next_pose = root @ self.matrix(shifted)
            dp, dr = pose_errors(current, next_pose)
            jacobian[:, index] = np.r_[dp, dr] / 1e-5
        delta = jacobian.T @ np.linalg.solve(
            jacobian @ jacobian.T + 0.05**2 * np.eye(6), error
        )
        limits = np.asarray(limits, dtype=np.float64)
        if limits.shape != (len(joints), 2) or not np.isfinite(limits).all():
            raise ValueError("Finite per-joint limits required")
        low = np.maximum(limits[:, 0], joints - 0.05)
        high = np.minimum(limits[:, 1], joints + 0.05)
        if np.any(low > high):
            raise ValueError("Joint outside bounded valid interval")
        result = np.clip(joints + delta, low, high)
        return result, {
            "target_position_error_m": float(np.linalg.norm(translation)),
            "target_rotation_error_rad": float(np.linalg.norm(rotation)),
            "proposed_joint_delta": (result - joints).tolist(),
            "bounded_task_delta": error.tolist(),
        }


class DualKinematics:
    """Read current robot geometry and solve one step without physics previews."""

    def __init__(self, env: Any):
        self.manager = env.robot_manager
        self.robots = {
            robot.arm_name.split("_")[0]: robot
            for robot in self.manager.robot_list
            if robot.type == "target"
        }
        if set(self.robots) != {"left", "right"}:
            raise ValueError("Expected left/right target X5 arms")
        self.fk = {
            arm: ArmFK(
                robot.urdf_path,
                robot.arm_joints_name,
                robot.base_link,
                robot.ee_link_name,
            )
            for arm, robot in self.robots.items()
        }

    def root(self, arm: str) -> np.ndarray:
        """Return the measured robot base in environment-origin coordinates."""
        robot = self.robots[arm]
        value = self.manager.get_link_pose(robot, robot.base_link, is_relative=True)[0]
        return transform(value[:3], value[3:])

    def check(self) -> dict:
        """Reject geometry whose FK disagrees with measured EEF poses."""
        checks = {}
        for arm, robot in self.robots.items():
            joints = self.manager.get_joint(robot)[0]
            predicted = self.root(arm) @ self.fk[arm].matrix(joints)
            measured = self.manager.get_real_endpose(robot)[0]
            dp, dr = pose_errors(predicted, transform(measured[:3], measured[3:]))
            checks[arm] = {
                "position_error_m": float(np.linalg.norm(dp)),
                "rotation_error_rad": float(np.linalg.norm(dr)),
                "passed": bool(
                    np.linalg.norm(dp) < 0.002 and np.linalg.norm(dr) < 0.01
                ),
            }
        if not all(check["passed"] for check in checks.values()):
            raise ValueError(f"Robot FK does not match measured link6: {checks}")
        return checks

    def target(self, targets: dict) -> tuple[dict, dict]:
        """Return one native joint dict; do not execute or simulate it."""
        checks = self.check()
        action, diagnostics = {}, {}
        for arm, robot in self.robots.items():
            key = self.manager.robot_key[self.manager.robot_list.index(robot)]
            limits = (
                key.data.soft_joint_pos_limits[0, robot.arm_joint_indices].cpu().numpy()
            )
            joints, diagnostics[arm] = self.fk[arm].bounded_target(
                self.manager.get_joint(robot)[0], limits, self.root(arm), targets[arm]
            )
            action[f"{arm}_arm_joint_state"] = joints.tolist()
            action[f"{arm}_ee_joint_state"] = [
                float(not targets[arm]["gripper_closed"])
            ]
        return action, {"fk_check": checks, "arms": diagnostics}
