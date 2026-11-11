# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Opt-in short EEF targets on the existing LIBERO OSC controller."""

from __future__ import annotations

from typing import Annotated, Any

import numpy as np
from pydantic import Field

from rpent.tools import ToolResult, tool


class ControllerObservation:
    """Delegate the environment unchanged and expose robot-only controller data."""

    def __init__(self, env: Any):
        self.env = env

    def __getattr__(self, name: str) -> Any:
        return getattr(self.env, name)

    @property
    def eef_controller_state(self) -> dict:
        """Read live controller parameters through RLinf's existing getattr IPC."""
        robot = self.env.robots[0]
        controller = getattr(robot, "part_controllers", {}).get("right")
        low, high = self.env.env.action_spec
        if (
            type(controller).__name__ != "OperationalSpaceController"
            or controller.impedance_mode != "fixed"
            or controller.input_type != "delta"
            or controller._goal_update_mode != "achieved"
            or controller.input_ref_frame not in {"world", "base"}
            or len(low) != 7
        ):
            return {
                "error": "move_eef requires seven-dimensional fixed delta OSC_POSE with achieved goals"
            }
        return {
            "frame": controller.input_ref_frame,
            "origin_ori": np.asarray(controller.origin_ori).tolist()
            if controller.input_ref_frame == "base"
            else np.eye(3).tolist(),
            **{
                name: np.asarray(getattr(controller, name)).tolist()
                for name in ("input_min", "input_max", "output_min", "output_max")
            },
            "action_low": np.asarray(low).tolist(),
            "action_high": np.asarray(high).tolist(),
        }


def with_controller_observation(factory: Any) -> ControllerObservation:
    """Wrap only explicitly enabled, fixed-task evaluation environments."""
    return ControllerObservation(factory())


def target_action(
    xyz: np.ndarray, rotation: Any, raw: dict, config: dict
) -> np.ndarray:
    """Convert a world target into bounded inputs using the active OSC scaling."""
    from scipy.spatial.transform import Rotation

    if "error" in config:
        raise ValueError(config["error"])
    current = Rotation.from_quat(raw["robot0_eef_quat"])
    world_delta = np.r_[
        xyz - raw["robot0_eef_pos"], (rotation * current.inv()).as_rotvec()
    ]
    basis = np.asarray(config["origin_ori"], dtype=float)
    delta = np.r_[basis.T @ world_delta[:3], basis.T @ world_delta[3:]]
    lo, hi = (np.asarray(config[k], dtype=float) for k in ("output_min", "output_max"))
    ilo, ihi = (np.asarray(config[k], dtype=float) for k in ("input_min", "input_max"))
    if any(a.shape != (6,) for a in (lo, hi, ilo, ihi)) or np.any(hi <= lo):
        raise ValueError(
            "move_eef requires six OSC dimensions with increasing scaling bounds"
        )
    # Scale each vector uniformly before the controller's per-axis clipping.
    # This retains its direction even when the target exceeds one native step.
    for part in (slice(0, 3), slice(3, 6)):
        limits = np.where(delta[part] >= 0, hi[part], -lo[part])
        if np.any(limits <= 0):
            raise ValueError("move_eef requires OSC output bounds spanning zero")
        delta[part] /= max(1.0, float(np.max(np.abs(delta[part]) / limits)))
    return np.clip(ilo + (delta - lo) * (ihi - ilo) / (hi - lo), ilo, ihi)


class EefControl:
    """Use existing primitive stepping, recording and cancellation checkpoints."""

    def __init__(self, primitives: Any):
        self.primitives = primitives

    @tool
    def move_eef(
        self,
        xyz: Annotated[list[float], Field(min_length=3, max_length=3)],
        quat_xyzw: Annotated[list[float], Field(min_length=4, max_length=4)],
        gripper: Annotated[float, Field(ge=-1, le=1)],
        steps: Annotated[int, Field(ge=1, le=10, strict=True)] = 5,
    ) -> ToolResult:
        """Move briefly toward one world-frame EEF pose, then inspect updated images and measured pose.

        xyz is metres; quat_xyzw is a unit quaternion in the same frame as
        robot0_eef_quat. gripper is -1 open, +1 close, 0 retains the command.
        Execute 1..10 environment control steps (default 5), including gripper
        updates when the pose already matches. Arrival and collision avoidance
        are not guaranteed. Use returned pose errors and object motion to choose
        the next target; EEF arrival does not establish task completion.
        """
        from scipy.spatial.transform import Rotation

        xyz, quat = np.asarray(xyz, dtype=float), np.asarray(quat_xyzw, dtype=float)
        if (
            xyz.shape != (3,)
            or quat.shape != (4,)
            or not np.isfinite(np.r_[xyz, quat, gripper]).all()
            or not np.isclose(np.linalg.norm(quat), 1.0, atol=1e-3, rtol=0)
            or not -1 <= gripper <= 1
            or type(steps) is not int
            or not 1 <= steps <= 10
        ):
            raise ValueError(
                "Supply finite xyz, a unit xyzw quaternion, gripper in [-1,1], and integer steps in [1,10]"
            )
        p = self.primitives
        if p.env.terminated or p.env.truncated:
            return ToolResult(data={"error": "Environment episode ended"})
        target = Rotation.from_quat(quat)
        executed = 0
        for _ in range(steps):
            p._check_cancelled()
            config = p.env.get_eef_controller_state()
            arm = target_action(xyz, target, p.env.raw_obs(), config)
            action = np.r_[arm, gripper]
            if (
                not np.isfinite(action).all()
                or np.any(action < config["action_low"])
                or np.any(action > config["action_high"])
            ):
                raise ValueError("Converted EEF action exceeds native action bounds")
            p._step_env(action)
            executed += 1
            if p.env.terminated or p.env.truncated:
                break
        raw = p.env.raw_obs()
        return ToolResult(
            data={
                "name": "move_eef",
                "steps_used": executed,
                "max_steps": steps,
                "target_xyz": xyz.tolist(),
                "target_quat_xyzw": target.as_quat().tolist(),
                "final_eef_pos": np.asarray(raw["robot0_eef_pos"]).tolist(),
                "final_eef_quat_xyzw": np.asarray(raw["robot0_eef_quat"]).tolist(),
                "position_error_m": float(np.linalg.norm(xyz - raw["robot0_eef_pos"])),
                "orientation_error_rad": float(
                    (
                        target * Rotation.from_quat(raw["robot0_eef_quat"]).inv()
                    ).magnitude()
                ),
                "terminated": bool(p.env.terminated),
                "truncated": bool(p.env.truncated),
            }
        )
