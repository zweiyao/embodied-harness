# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Observable contracts for short world-frame EEF commands."""

from types import SimpleNamespace

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from robots.libero.eef_control import ControllerObservation, EefControl, target_action
from robots.libero.tools import LiberoPrimitives
from rpent.dashboard.workbench import native_catalog


def config(basis=None):
    return {
        "origin_ori": np.eye(3) if basis is None else basis,
        "input_min": [-1] * 6,
        "input_max": [1] * 6,
        "output_min": [-0.05] * 3 + [-0.5] * 3,
        "output_max": [0.05] * 3 + [0.5] * 3,
        "action_low": [-1] * 7,
        "action_high": [1] * 7,
    }


class Env:
    def __init__(self):
        self.terminated = self.truncated = False
        self.position = np.zeros(3)
        self.rotation = Rotation.identity()
        self.actions = []
        self.stop_after = None

    def get_eef_controller_state(self):
        return config()

    def raw_obs(self):
        return {
            "robot0_eef_pos": self.position.copy(),
            "robot0_eef_quat": self.rotation.as_quat(),
        }

    def step(self, action):
        self.actions.append(action.copy())
        self.position += action[:3] * 0.05
        self.rotation = Rotation.from_rotvec(action[3:6] * 0.5) * self.rotation
        self.truncated = len(self.actions) == self.stop_after
        obs = {
            "states": np.r_[self.position, np.zeros(5)],
            "main_images": np.full((2, 2, 3), len(self.actions), dtype=np.uint8),
        }
        return obs, 0, self.terminated, self.truncated, {}


def primitive(env, check=lambda: None):
    result = LiberoPrimitives(env, None, None, check)
    result.start_recording()
    return result


@pytest.mark.parametrize("axis", range(3))
def test_world_frame_translation_and_rotation(axis):
    basis = Rotation.from_euler("z", 90, degrees=True).as_matrix()
    raw = {"robot0_eef_pos": np.zeros(3), "robot0_eef_quat": [0, 0, 0, 1]}
    xyz = np.eye(3)[axis] * 0.01
    target = Rotation.from_rotvec(np.eye(3)[axis] * 0.1)
    action = target_action(xyz, target, raw, config(basis))
    np.testing.assert_allclose(basis @ (action[:3] * 0.05), xyz, atol=1e-12)
    np.testing.assert_allclose(
        basis @ (action[3:] * 0.5), target.as_rotvec(), atol=1e-12
    )


def test_rotations_are_composed_in_world_frame_not_euler_subtracted():
    current = Rotation.from_euler("xyz", [1.0, 0.3, -0.7])
    delta = Rotation.from_rotvec([0.03, -0.05, 0.07])
    raw = {"robot0_eef_pos": np.zeros(3), "robot0_eef_quat": current.as_quat()}
    action = target_action(np.zeros(3), delta * current, raw, config())
    np.testing.assert_allclose(action[3:] * 0.5, delta.as_rotvec(), atol=1e-12)


def test_short_execution_records_images_and_still_commands_gripper_at_target():
    env = Env()
    p = primitive(env)
    out = EefControl(p).move_eef([0, 0, 0], [0, 0, 0, 1], 1, steps=5)
    assert out.data["steps_used"] == 5
    assert len(p.frame_slice(0)) == 5
    assert all(a[6] == 1 for a in env.actions)
    assert out.data["position_error_m"] == 0
    assert p._last_obs["main_images"][0, 0, 0] == 5


def test_distant_target_stops_at_budget_and_reports_remaining_error():
    env = Env()
    out = EefControl(primitive(env)).move_eef([1, 0.5, 0], [0, 0, 0, 1], -1, steps=2)
    assert out.data["steps_used"] == 2
    assert out.data["position_error_m"] > 0.9
    assert all(np.max(np.abs(a)) <= 1 for a in env.actions)
    np.testing.assert_allclose(env.actions[0][:3], [1, 0.5, 0])


def test_stops_immediately_on_truncation_and_rejects_further_actions():
    env = Env()
    env.stop_after = 2
    control = EefControl(primitive(env))
    out = control.move_eef([0.1, 0, 0], [0, 0, 0, 1], -1)
    assert out.data["steps_used"] == 2
    assert control.move_eef([0, 0, 0], [0, 0, 0, 1], 1).is_error
    assert len(env.actions) == 2


def test_cancellation_prevents_motion():
    env = Env()

    def cancelled():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        EefControl(primitive(env, cancelled)).move_eef([0, 0, 0], [0, 0, 0, 1], 1)
    assert env.actions == []


@pytest.mark.parametrize(
    "override",
    [
        {"xyz": [float("nan"), 0, 0]},
        {"xyz": [0, 0]},
        {"quat_xyzw": [0, 0, 0, 0]},
        {"quat_xyzw": [1, 1, 0, 0]},
        {"gripper": 2},
        {"steps": 0},
        {"steps": 11},
        {"steps": True},
    ],
)
def test_invalid_input_does_not_advance_environment(override):
    env = Env()
    kwargs = {"xyz": [0, 0, 0], "quat_xyzw": [0, 0, 0, 1], "gripper": 1, **override}
    with pytest.raises(ValueError):
        EefControl(primitive(env)).move_eef(**kwargs)
    assert not env.actions


def test_controller_query_uses_live_values_and_no_object_state():
    attrs = config()
    controller_type = type("OperationalSpaceController", (), {})
    controller = controller_type()
    for name in ("input_min", "input_max", "output_min", "output_max"):
        setattr(controller, name, attrs[name])
    controller.origin_ori = np.eye(3)
    controller.impedance_mode = "fixed"
    controller.input_type = "delta"
    controller._goal_update_mode = "achieved"
    controller.input_ref_frame = "base"
    wrapper = ControllerObservation(
        SimpleNamespace(
            robots=[SimpleNamespace(part_controllers={"right": controller})],
            env=SimpleNamespace(action_spec=([-1] * 7, [1] * 7)),
        )
    )
    assert set(wrapper.eef_controller_state) == set(attrs) | {"frame"}
    controller.output_max = [0.02] * 6
    assert wrapper.eef_controller_state["output_max"] == [0.02] * 6
    controller._goal_update_mode = "desired"
    assert "error" in wrapper.eef_controller_state
    del wrapper.env.robots[0].part_controllers
    assert "error" in wrapper.eef_controller_state


def test_catalog_exposes_optional_control_without_changing_original_primitives():
    from rpent.tools import iter_tools

    item = next(t for t in native_catalog() if t["name"] == "move_eef")
    assert item["category"] == "control" and not item["required"]
    assert item["parameters"]["required"] == ["xyz", "quat_xyzw", "gripper"]
    assert "move_eef" not in {t.name for t in iter_tools(LiberoPrimitives)}


def test_default_selection_and_prompt_do_not_enable_eef():
    from robots.libero.research.manual import availability_prompt
    from rpent.dashboard.workbench import Workbench

    wb = Workbench.__new__(Workbench)
    wb.robot = "libero"
    wb.catalog = lambda: [{**t, "selectable": True} for t in native_catalog()]
    assert "move_eef" not in {t["name"] for t in wb.selection()}
    assert "next short move_eef" not in availability_prompt(wb.selection())
    selected = wb.selection(["native:move_eef", "native:finish"])
    assert "next short move_eef" in availability_prompt(selected)


@pytest.mark.parametrize("enabled", [False, True])
def test_workbench_selection_enables_only_its_own_environment(
    monkeypatch, tmp_path, enabled
):
    from robots.libero import robot_spec

    captured = {}

    def daemon(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(robot_spec, "ProcessDaemon", daemon)
    args = SimpleNamespace(
        env_endpoint=None,
        suite="libero_10_task",
        task=0,
        seed=0,
        max_episode_steps=100,
        cuda_device=None,
        libero_type="pro",
        frozen_tools=[{"name": "move_eef"}] if enabled else [{"name": "move_to"}],
    )
    robot_spec._spawn_env_server(args, tmp_path)
    assert ("--enable-eef-control" in captured["cmd"]) is enabled
