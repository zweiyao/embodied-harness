# Copyright 2026 The TacTalent Contributors and The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Short Panda hand commands using native UniVTAC/curobo control.

Adapted from TacTalent 75441c18c3054b6032c4923f4047b9deaef26694,
src/tactalent/roboicl/controller.py (Apache-2.0; see _panda/NOTICE.md).
"""

from __future__ import annotations

import numpy as np

from ._panda.ik import _Backend
from ._panda.state import RobotObserver
from ._panda.transforms import orientation_error, quaternion, vector

ACTION_REPEAT = 2
COMMAND_LIMIT = 300
CHUNK_LIMIT = 5
MAX_JOINT_INCREMENT = 0.15


def validate_command(values):
    """World hand pose (m, wxyz) followed by normalized finger opening."""
    action = vector(values, 8)
    action[3:7] = quaternion(action[3:7])
    if not 0 <= action[7] <= 1:
        raise ValueError("gripper must be in [0, 1]")
    return action


def native_status(task):
    """Evaluator-only termination details; never include these in observations."""
    success = bool(task.eval_success)
    early_stop = bool(task.check_early_stop())
    exhausted = int(task.take_action_cnt) >= int(task.cfg.step_lim)
    plan_failed = not bool(task.plan_success)
    return {
        "official_success": success,
        "early_stop": early_stop,
        "budget_exhausted": exhausted,
        "plan_failed": plan_failed,
        "done": success or early_stop or exhausted or plan_failed,
    }


def apply_native(task, qpos):
    """One native action slot, up to two physical steps; no task heuristics."""
    if native_status(task)["done"]:
        raise RuntimeError("Cannot execute after native termination")
    before, physics = int(task.take_action_cnt), int(task.step_count)
    tensor = task._robot_manager.robot.data.joint_pos.new_tensor(qpos)
    initial = task._robot_manager.get_observations(["joint"])["joint"][:8].clone()
    ok, success = task.take_action(initial + (tensor - initial) / 2, "qpos", force=True)
    if ok and not success and task.plan_success and not task.check_early_stop():
        # The last action's second physics step does not charge another slot.
        task._robot_manager.set_arm(tensor[:-1], force=True)
        task._robot_manager.set_gripper(tensor[-1], force=True)
        task._step()
        if task.check_success():
            task.eval_success = True
    receipt = {
        "exec_success": bool(ok),
        "native_action_delta": int(task.take_action_cnt) - before,
        "physics_step_delta": int(task.step_count) - physics,
    }
    if receipt["native_action_delta"] != 1:
        raise RuntimeError("Unexpected native action counter change")
    if not 1 <= receipt["physics_step_delta"] <= ACTION_REPEAT:
        raise RuntimeError("Unexpected native physics cadence")
    return receipt


class PandaController:
    def __init__(self, task):
        self.task = task
        self.observer = RobotObserver({})
        names, _, _ = self.observer._joint_layout(task)
        self.backend = _Backend(task, names)
        self.fk_audit = self.observer.validate_fk(task)
        if not self.fk_audit["passed"]:
            raise RuntimeError(f"Native FK mismatch: {self.fk_audit}")
        if abs(float(task._robot_manager.gripper_max_qpos) - 0.039) > 1e-8:
            raise RuntimeError("Unexpected Panda gripper range")

    def execute(self, values):
        from scipy.spatial.transform import Rotation

        action = validate_command(values)
        state = self.observer.observe_state(self.task)
        prior = np.asarray(state["qpos"][:7])
        root = state["root_pose_w"]
        rotation = Rotation.from_quat(np.asarray(root["quaternion_wxyz"])[[1, 2, 3, 0]])
        position = rotation.inv().apply(action[:3] - root["position"])
        orientation = (
            rotation.inv() * Rotation.from_quat(action[3:7][[1, 2, 3, 0]])
        ).as_quat()[[3, 0, 1, 2]]
        bias = np.asarray(getattr(self.backend.planner, "frame_bias", [0, 0, 0]))
        solutions = self.backend.solve(position + bias, orientation, prior)
        candidates = [
            candidate
            for candidate in solutions
            if np.max(np.abs(candidate - prior)) <= MAX_JOINT_INCREMENT + 1e-6
        ]
        if not candidates:
            return {
                "exec_success": False,
                "reason": "IK unavailable or exceeds continuity limit",
                "max_joint_increment_rad": MAX_JOINT_INCREMENT,
                "native_action_delta": 0,
                "physics_step_delta": 0,
            }
        target = min(candidates, key=lambda value: np.linalg.norm(value - prior))
        receipt = apply_native(self.task, np.r_[target, action[7] * 0.039])
        observed = self.observer.observe_state(self.task)
        from ._panda.transforms import compose

        root = observed["root_pose_w"]
        hand = observed["hand_pose"]
        position, orientation = compose(
            root["position"],
            root["quaternion_wxyz"],
            hand["position"],
            hand["quaternion_wxyz"],
        )
        receipt["position_error_m"] = float(np.linalg.norm(position - action[:3]))
        receipt["orientation_error_rad"] = orientation_error(orientation, action[3:7])
        return receipt
