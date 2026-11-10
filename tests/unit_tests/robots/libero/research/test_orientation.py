# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Bounded world-axis rotation, retained position and native feedback."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from robots.libero.eef_control import target_action
from robots.libero.research.orientation import OrientationControl
from tests.unit_tests.robots.libero.test_eef_control import Env, config, primitive


@pytest.mark.parametrize("axis", ["x", "z"])
@pytest.mark.parametrize("angle", [-0.3, 0.3])
def test_rotation_is_relative_to_world_axis_and_keeps_starting_xyz(axis, angle):
    env = Env()
    env.position = np.array([0.1, -0.2, 0.3])
    initial = Rotation.from_euler("xyz", [0.6, -0.4, 0.7])
    env.rotation = initial
    p = primitive(env)
    result = OrientationControl(p).rotate_axis(axis, angle).data
    expected = Rotation.from_rotvec(
        np.array([1, 0, 0] if axis == "x" else [0, 0, 1]) * angle
    )
    np.testing.assert_allclose(
        (env.rotation * initial.inv()).as_matrix(), expected.as_matrix(), atol=1e-12
    )
    np.testing.assert_allclose(env.position, [0.1, -0.2, 0.3], atol=1e-12)
    assert result["target_reached"]
    assert len(env.actions) == result["steps_used"] == p.recorded_frame_count() == 10
    assert all(action[6] == 0 for action in env.actions)


def test_feedback_restores_frozen_position_after_injected_deviation():
    env = Env()
    env.position = np.array([0.1, -0.2, 0.3])
    saved_target = env.position.copy()
    original_step = env.step
    gripper_target = np.array([0.6, -0.6])

    def disturbed_step(action):
        nonlocal gripper_target
        if action[6] != 0:
            gripper_target += action[6]
        obs, reward, terminated, truncated, info = original_step(action)
        if len(env.actions) == 1:
            env.position += np.array([0.025, -0.02, 0.015])
        obs["states"][:3] = env.position
        return obs, reward, terminated, truncated, info

    env.step = disturbed_step
    result = OrientationControl(primitive(env)).rotate_axis("z", 0.3).data
    # Correction is present in the second native action, within the same chunk.
    np.testing.assert_allclose(env.actions[1][:3], [-0.5, 0.4, -0.3], atol=1e-12)
    np.testing.assert_allclose(env.position, saved_target, atol=1e-12)
    np.testing.assert_array_equal(gripper_target, [0.6, -0.6])
    assert result["position_error_m"] < 1e-12


@pytest.mark.parametrize("axis", ["x", "z"])
def test_first_rotation_command_uses_actual_nonidentity_basis_and_scale(axis):
    env = Env()
    basis = Rotation.from_euler("xyz", [0.2, 0.3, -0.4]).as_matrix()
    actual = config(basis)
    actual["output_min"] = [-0.03] * 3 + [-0.4] * 3
    actual["output_max"] = [0.03] * 3 + [0.4] * 3
    env.get_eef_controller_state = lambda: actual
    # Terminate after the first action: this test checks controller input,
    # not the inherited fake's different motion scaling.
    env.stop_after = 1
    OrientationControl(primitive(env)).rotate_axis(axis, 0.08)
    expected = np.array([0.08, 0, 0] if axis == "x" else [0, 0, 0.08])
    np.testing.assert_allclose(
        basis @ (env.actions[0][3:6] * 0.4),
        expected,
        rtol=0,
        atol=8 * np.finfo(float).eps,
    )
    np.testing.assert_array_equal(env.actions[0][:3], [0, 0, 0])


def test_body_site_constant_rotation_offset_cancels_in_global_residual():
    start = Rotation.from_euler("xyz", [0.4, -0.7, 0.8])
    current = Rotation.from_euler("xyz", [0.3, -0.5, 0.9])
    offset = Rotation.from_euler("xyz", [-0.2, 0.6, -1.1])
    requested = Rotation.from_rotvec([0, 0, 0.3])
    desired_body = requested * start
    desired_site = requested * start * offset
    current_site = current * offset
    np.testing.assert_allclose(
        (desired_body * current.inv()).as_matrix(),
        (desired_site * current_site.inv()).as_matrix(),
        atol=1e-12,
    )
    basis = Rotation.from_euler("y", 0.2).as_matrix()
    raw = {"robot0_eef_pos": np.zeros(3), "robot0_eef_quat": current.as_quat()}
    action = target_action(np.zeros(3), desired_body, raw, config(basis))
    reconstructed = Rotation.from_rotvec(basis @ (action[3:] * 0.5)) * current_site
    np.testing.assert_allclose(
        reconstructed.as_matrix(), desired_site.as_matrix(), atol=1e-12
    )


def test_stall_has_finite_actual_action_count_and_reports_remaining_error():
    env = Env()
    original_step = env.step

    def stalled_step(action):
        rotation = env.rotation
        result = original_step(action)
        env.rotation = rotation
        return result

    env.step = stalled_step
    p = primitive(env)
    result = OrientationControl(p).rotate_axis("x", 0.3).data
    assert not result["target_reached"]
    assert result["orientation_error_rad"] == pytest.approx(0.3)
    assert result["steps_used"] == result["max_steps"] == len(env.actions) == 40
    assert p.recorded_frame_count() == 40


def test_zero_angle_performs_no_control_steps():
    env = Env()
    result = OrientationControl(primitive(env)).rotate_axis("z", 0.0).data
    assert result["steps_used"] == 0 and result["target_reached"]
    assert not env.actions


@pytest.mark.parametrize(
    "axis, angle", [("y", 0.2), ("x", True), ("x", float("nan")), ("z", 3.2)]
)
def test_invalid_input_does_not_advance_environment(axis, angle):
    env = Env()
    with pytest.raises(ValueError):
        OrientationControl(primitive(env)).rotate_axis(axis, angle)
    assert not env.actions


def test_truncation_and_midway_cancellation_stop_without_another_chunk():
    env = Env()
    env.stop_after = 2
    control = OrientationControl(primitive(env))
    assert control.rotate_axis("x", 0.3).data["truncated"]
    assert control.rotate_axis("z", 0.3).is_error
    assert len(env.actions) == 2
    env = Env()

    def cancelled():
        if len(env.actions) >= 3:
            raise RuntimeError("cancelled")

    p = primitive(env, cancelled)
    with pytest.raises(RuntimeError, match="cancelled"):
        OrientationControl(p).rotate_axis("z", 0.3)
    assert len(env.actions) == p.recorded_frame_count() == 3


def test_rotation_is_optional_and_versions_include_its_module():
    import hashlib
    import inspect

    from robots.libero.research import orientation
    from robots.libero.research.manual import availability_prompt
    from rpent.dashboard.workbench import Workbench, native_catalog

    catalog = native_catalog()
    item = next(t for t in catalog if t["name"] == "rotate_axis")
    assert item["category"] == "control" and not item["required"]
    assert item["dependencies"] == []
    assert set(item["parameters"]["properties"]) == {"axis", "angle_rad"}
    assert set(item["parameters"]["required"]) == {"axis", "angle_rad"}
    assert (
        item["version"]
        == hashlib.sha256(inspect.getsource(orientation).encode()).hexdigest()
    )
    wb = Workbench.__new__(Workbench)
    wb.robot = "libero"
    wb.catalog = lambda: [{**t, "selectable": True} for t in catalog]
    default = wb.selection()
    assert "rotate_axis" not in {t["name"] for t in default}
    assert {"rotate_wrist", "rotate_pitch"} <= {t["name"] for t in default}
    assert "rotate_axis" not in availability_prompt(default)
    selected = wb.selection(["native:rotate_axis", "native:finish"])
    assert "Use rotate_axis for relative world-axis rotation" in availability_prompt(
        selected
    )
    assert "next short move_eef" not in availability_prompt(selected)
