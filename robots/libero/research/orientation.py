# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Optional relative world-axis rotation through the existing EEF controller."""

from __future__ import annotations

from typing import Annotated, Any, Literal

import numpy as np
from pydantic import Field

from robots.libero.eef_control import EefControl
from robots.libero.tools import LiberoPrimitives
from rpent.tools import ToolResult, tool


class OrientationControl:
    """Freeze one robot target and reuse native stepping and feedback."""

    def __init__(self, primitives: Any):
        self.primitives = primitives

    @tool
    def rotate_axis(
        self,
        axis: Literal["x", "z"],
        angle_rad: Annotated[
            float, Field(ge=-np.pi, le=np.pi, strict=True, allow_inf_nan=False)
        ],
    ) -> ToolResult:
        """Rotate relative to world x or z, retaining starting XYZ and the gripper target.

        angle_rad is a signed right-hand rotation in [-pi, pi], not an Euler
        angle target. Uses up to 40 native control steps with pose feedback.
        Inspect returned images and errors; contact clearance and grasp are not
        guaranteed. Change the fingers separately with set_gripper or release.
        """
        from scipy.spatial.transform import Rotation

        if (
            axis not in {"x", "z"}
            or isinstance(angle_rad, bool)
            or not np.isfinite(angle_rad)
            or not -np.pi <= angle_rad <= np.pi
        ):
            raise ValueError("Supply world axis x or z and a finite angle in [-pi, pi]")
        p = self.primitives
        p._check_cancelled()
        if p.env.terminated or p.env.truncated:
            return ToolResult(data={"error": "Environment episode ended"})
        raw = p.env.raw_obs()
        xyz = np.asarray(raw["robot0_eef_pos"], dtype=float).copy()
        start = Rotation.from_quat(raw["robot0_eef_quat"])
        vector = np.array([1.0, 0.0, 0.0] if axis == "x" else [0.0, 0.0, 1.0])
        target = Rotation.from_rotvec(vector * angle_rad) * start
        position_tol = LiberoPrimitives.move_to.args_schema.model_fields["tol"].default
        angle_tol = LiberoPrimitives.rotate_wrist.args_schema.model_fields[
            "tol"
        ].default
        control = EefControl(p)

        def errors(observation):
            return (
                float(np.linalg.norm(xyz - observation["robot0_eef_pos"])),
                float(
                    (
                        target
                        * Rotation.from_quat(observation["robot0_eef_quat"]).inv()
                    ).magnitude()
                ),
            )

        executed = 0
        for _ in range(4):
            position_error, angle_error = errors(raw)
            if position_error < position_tol and angle_error < angle_tol:
                break
            result = control.move_eef(
                xyz.tolist(), target.as_quat().tolist(), gripper=0.0, steps=10
            )
            if result.is_error:
                return result
            executed += result.data["steps_used"]
            raw = p.env.raw_obs()
            if p.env.terminated or p.env.truncated:
                break
        position_error, angle_error = errors(raw)
        return ToolResult(
            data={
                "name": "rotate_axis",
                "axis": axis,
                "angle_rad": float(angle_rad),
                "target_xyz": xyz.tolist(),
                "target_quat_xyzw": target.as_quat().tolist(),
                "final_eef_pos": np.asarray(raw["robot0_eef_pos"]).tolist(),
                "final_eef_quat_xyzw": np.asarray(raw["robot0_eef_quat"]).tolist(),
                "position_error_m": position_error,
                "orientation_error_rad": angle_error,
                "position_tolerance_m": position_tol,
                "orientation_tolerance_rad": angle_tol,
                "target_reached": position_error < position_tol
                and angle_error < angle_tol,
                "steps_used": executed,
                "max_steps": 40,
                "gripper_command": 0.0,
                "terminated": bool(p.env.terminated),
                "truncated": bool(p.env.truncated),
            }
        )
