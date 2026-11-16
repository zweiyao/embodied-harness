# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Short EEF commands preserve feedback, bounds, and the original mode."""

import copy
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from robots.robodojo.catalog import native_catalog, validate_selection
from robots.robodojo.eef_control import ArmFK, pose_errors, transform, validate_targets
from robots.robodojo.prompt_bundle import system_prompt
from robots.robodojo.toolkit import RoboDojoToolkit
from rpent.dashboard.events import NullDashboardEventSink
from rpent.memory import MemoryManager


def target():
    return {
        arm: {
            "position": [0.0, 0.0, 0.0],
            "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            "gripper_closed": arm == "left",
        }
        for arm in ("left", "right")
    }


def state():
    return {
        f"{arm}_ee_pose": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        for arm in ("left", "right")
    }


@pytest.mark.parametrize(
    "change",
    ["missing_arm", "nan", "quaternion", "distance", "rotation", "gripper", "extra"],
)
def test_invalid_targets_rejected_before_motion(change):
    value = target()
    if change == "missing_arm":
        value.pop("right")
    elif change == "nan":
        value["left"]["position"][0] = float("nan")
    elif change == "quaternion":
        value["right"]["quaternion_wxyz"] = [0.0] * 4
    elif change == "distance":
        value["right"]["position"][0] = 0.051
    elif change == "rotation":
        quat = Rotation.from_rotvec([0.0, 0.0, 0.351]).as_quat()
        value["right"]["quaternion_wxyz"] = quat[[3, 0, 1, 2]].tolist()
    elif change == "gripper":
        value["right"]["gripper_closed"] = "false"
    else:
        value["right"]["gripper_opening"] = 0.5
    with pytest.raises(ValueError):
        validate_targets(value, state(), 1)


@pytest.mark.parametrize("steps", [0, 6, True, 1.5])
def test_invalid_step_count(steps):
    with pytest.raises(ValueError, match="steps"):
        validate_targets(target(), state(), steps)


def test_quaternion_wxyz_and_equivalent_sign():
    quat = Rotation.from_rotvec([0.0, 0.0, 0.3]).as_quat()[[3, 0, 1, 2]]
    current = transform([0, 0, 0], quat)
    equivalent = transform([0, 0, 0], -quat)
    np.testing.assert_allclose(pose_errors(current, equivalent)[1], 0, atol=1e-12)
    np.testing.assert_allclose(
        current[:3, :3] @ [1, 0, 0], [np.cos(0.3), np.sin(0.3), 0]
    )


def test_dls_reduces_pose_error_and_respects_joint_limit(tmp_path):
    urdf = tmp_path / "arm.urdf"
    urdf.write_text("""<robot name="arm">
      <joint name="j1" type="revolute"><parent link="base"/><child link="link1"/><axis xyz="0 0 1"/></joint>
      <joint name="fixed" type="fixed"><parent link="link1"/><child link="tip"/><origin xyz="1 0 0"/></joint>
    </robot>""")
    fk = ArmFK(str(urdf), ["j1"], "base", "tip")
    value = {"position": [1.0, 0.02, 0.0], "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]}
    joints, info = fk.bounded_target([0.0], [[-0.005, 0.005]], np.eye(4), value)
    assert 0 < joints[0] <= 0.005
    assert abs(fk.matrix(joints)[1, 3] - 0.02) < 0.02
    assert np.linalg.norm(info["bounded_task_delta"][:3]) <= 0.02 + 1e-12
    # A rank-deficient six-dimensional task remains finite under damping.
    held, _ = fk.bounded_target(joints, [[-0.005, 0.005]], np.eye(4), value)
    assert np.isfinite(held).all()


def test_dls_rotation_and_joint_increment_are_bounded(tmp_path):
    urdf = tmp_path / "arm.urdf"
    urdf.write_text("""<robot name="arm"><joint name="j1" type="revolute">
      <parent link="base"/><child link="tip"/><axis xyz="0 0 1"/>
    </joint></robot>""")
    fk = ArmFK(str(urdf), ["j1"], "base", "tip")
    quaternion = Rotation.from_rotvec([0, 0, 0.3]).as_quat()[[3, 0, 1, 2]]
    joints, info = fk.bounded_target(
        [0],
        [[-3, 3]],
        np.eye(4),
        {"position": [0, 0, 0], "quaternion_wxyz": quaternion},
    )
    assert 0 < joints[0] <= 0.05
    assert np.linalg.norm(info["bounded_task_delta"][3:]) <= 0.1 + 1e-12


def selected(*names):
    return [item for item in native_catalog() if item["name"] in names]


@pytest.fixture
def toolkit(tmp_path, monkeypatch):
    from rpent.utils import logging

    monkeypatch.setattr(logging, "_output_dir", tmp_path)
    native_steps = []
    observation = {
        "state": state(),
        "vision": {
            cam: {"color": np.zeros((4, 4, 3), dtype=np.uint8)}
            for cam in ("cam_head", "cam_left_wrist", "cam_right_wrist")
        },
    }

    def step_eef(value):
        native_steps.append(copy.deepcopy(value))
        return {"status": {"step": len(native_steps), "step_limit": None}}

    env = SimpleNamespace(
        get_obs=lambda: observation,
        get_status=lambda: {"step": len(native_steps), "step_limit": None},
        get_task_language=lambda: "Official task instruction.",
        step_eef=step_eef,
    )
    result = RoboDojoToolkit(
        primitives_kwargs={"env": env},
        dashboard_events=NullDashboardEventSink(),
        memory=MemoryManager(tmp_path / "memory"),
        selected=selected("move_eef", "view_env_state", "finish"),
    )
    yield result, native_steps
    result.close()


def test_tool_returns_fresh_three_camera_feedback_and_rejects_stale_action(toolkit):
    tool, calls = toolkit
    initial = tool.execute_tool("view_env_state", {}).data["step"]
    args = {"observation_step": initial, "target": target(), "steps": 2}
    result = tool.execute_tool("move_eef", args)
    assert not result.is_error
    assert len(calls) == 2 and calls[0]["left"]["gripper_closed"] is True
    assert len(result.images) == 3 and result.data["step"] > initial
    assert result.data["log"]["result"]["steps_used"] == 2
    stale = tool.execute_tool("move_eef", args)
    assert "Stale observation_step" in stale.data["error"]
    assert len(calls) == 2
    assert len(stale.images) == 3
    assert "unknown tool" in tool.execute_tool("pi0_pick", {}).data["error"]


def test_bad_second_arm_causes_zero_control_steps(toolkit):
    tool, calls = toolkit
    value = target()
    value["right"]["position"] = [1.0, 0.0, 0.0]
    args = {"observation_step": tool.state.latest_record().step_idx, "target": value}
    response = tool.execute_tool("move_eef", args)
    assert not response.is_error
    assert response.data["log"]["result"]["replan_required"] is True
    assert response.data["log"]["result"]["steps_used"] == 0
    assert len(response.images) == 3
    assert calls == []


def test_cancel_checked_between_real_steps(toolkit, monkeypatch):
    tool, calls = toolkit

    def cancelled():
        if calls:
            raise RuntimeError("cancelled after ACK")

    monkeypatch.setattr(tool._primitives, "_check_cancelled", cancelled)
    args = {
        "observation_step": tool.state.latest_record().step_idx,
        "target": target(),
        "steps": 5,
    }
    assert tool.execute_tool("move_eef", args).is_error
    assert len(calls) == 1


@pytest.mark.parametrize(
    "other", ["pi0_pick", "move_to", "set_gripper", "stabilize", "place_in_bin"]
)
def test_eef_mode_cannot_include_other_action_tools(other):
    with pytest.raises(ValueError, match="without other motion"):
        validate_selection(selected("move_eef", "finish", other))


def test_opt_in_prompt_uses_feedback_without_policy_instructions():
    default = system_prompt({})
    assert "Pi_05" in default["ROBOT CONTROL"]
    eef = system_prompt({"manual_tools": selected("move_eef", "finish")})
    text = "\n".join(eef.values())
    assert "pi0_pick" not in text and "CuRobo" not in text
    assert "observation_step" in text and "wait for its returned" in text
    assert "Before finish, save a concise audit" in text


def test_native_eef_step_recomputes_after_ack_and_maps_grippers(
    make_agent, monkeypatch
):
    from robots.robodojo import eef_control
    from robots.robodojo.env_facade import RoboDojoEnvFacade

    native = SimpleNamespace(take_action_cnt=[0])
    agent = make_agent(native)
    actions = []

    class Kinematics:
        def __init__(self, env):
            assert env is native

        def target(self, targets):
            assert native.take_action_cnt[0] == len(actions)
            return {
                f"{arm}_ee_joint_state": [float(not targets[arm]["gripper_closed"])]
                for arm in ("left", "right")
            }, {"fk_check": "checked"}

    monkeypatch.setattr(eef_control, "DualKinematics", Kinematics)
    agent.get_obs = lambda: {"state": state()}

    def execute(action):
        actions.append(action)
        native.take_action_cnt[0] += 1
        return (
            {"state": state()},
            0.0,
            False,
            {
                "status": {
                    "step": len(actions),
                    "success": True,
                    "safety": {"private": True},
                }
            },
        )

    agent.step_native = execute
    facade = RoboDojoEnvFacade(agent)
    assert "env.step_eef" in facade._rpc
    assert "env.step_eef" not in facade._readonly_methods
    for index in range(2):
        response = facade.step_eef(target())
        assert response["native_step_before"] == index
        assert response["native_step_after"] == index + 1
        assert response["final"]["left"]["commanded_opening"] == 0.0
        assert response["final"]["right"]["commanded_opening"] == 1.0
        assert response["status"] == {"step": index + 1}
    # Invalid right-arm input must not execute even though the left arm is valid.
    value = target()
    value["right"]["quaternion_wxyz"] = [0.0] * 4
    with pytest.raises(ValueError):
        facade.step_eef(value)
    assert len(actions) == 2


def test_eef_rpc_is_not_available_in_eval_fair(make_agent):
    from robots.robodojo.env_facade import RoboDojoEnvFacade

    agent = make_agent(SimpleNamespace(), meta={"mode": "eval-fair"})
    assert "env.step_eef" not in RoboDojoEnvFacade(agent)._rpc
    with pytest.raises(ValueError, match="dev"):
        agent.step_eef(target())


def test_client_sends_short_step_without_reset():
    from robots.robodojo.env_client import RoboDojoEnvClient

    calls = []
    client = object.__new__(RoboDojoEnvClient)
    client._client = SimpleNamespace(
        call=lambda *args, **kwargs: calls.append((args, kwargs)) or {"ack": True}
    )
    assert client.step_eef(target()) == {"ack": True}
    assert calls == [(("env.step_eef",), {"kwargs": {"target": target()}})]


def test_default_toolkit_does_not_gain_eef_tool(tmp_path, monkeypatch):
    from rpent.utils import logging

    monkeypatch.setattr(logging, "_output_dir", tmp_path)
    env = SimpleNamespace(
        get_obs=lambda: {"vision": {}, "state": {}},
        get_status=lambda: {"step": 0, "step_limit": 10},
        get_task_language=lambda: "Official instruction.",
    )
    toolkit = RoboDojoToolkit(
        primitives_kwargs={"env": env},
        dashboard_events=NullDashboardEventSink(),
        memory=MemoryManager(tmp_path / "memory"),
    )
    names = {item.name for item in toolkit.list_tools()}
    assert "move_eef" not in names
    assert {"move_to", "set_gripper", "pi0_pick", "place_in_bin", "stabilize"} <= names
    toolkit.close()


def test_default_workbench_selection_keeps_original_actions(tmp_path):
    from rpent.dashboard.workbench import Workbench

    bench = Workbench(
        {
            "robot": "robodojo",
            "runs_root": str(tmp_path),
            "library_root": str(tmp_path / "library"),
            "models": [{"id": "fixture", "planner": "api", "model": "fixture"}],
        },
        robot="robodojo",
    )
    names = {item["name"] for item in bench.selection()}
    assert "move_eef" not in names and "pi0_pick" in names


@pytest.mark.parametrize("kind", ["distance", "rotation"])
def test_server_range_rejection_executes_no_native_control(
    make_agent, monkeypatch, kind
):
    from robots.robodojo import eef_control

    native = SimpleNamespace(take_action_cnt=[7])
    agent = make_agent(native, meta={"max_episode_steps": 0})
    agent.get_obs = lambda: {"state": state()}
    monkeypatch.setattr(
        eef_control,
        "DualKinematics",
        lambda _: pytest.fail("rejected target must not construct IK"),
    )
    value = target()
    if kind == "distance":
        value["right"]["position"] = [0.051, 0, 0]
    else:
        value["right"]["quaternion_wxyz"] = (
            Rotation.from_rotvec([0, 0, 0.351]).as_quat()[[3, 0, 1, 2]].tolist()
        )
    result = agent.step_eef(value)
    assert result["rejected"] and result["code"] == "eef_target_limit"
    assert result["native_step_before"] == result["native_step_after"] == 7
    assert native.take_action_cnt == [7]


def test_mid_chunk_range_rejection_preserves_prefix_and_next_decision(toolkit):
    tool, controls = toolkit
    env = tool._primitives.env
    observation = env.get_obs()
    calls = []

    def step(value):
        calls.append(copy.deepcopy(value))
        if len(calls) == 3:
            observation["state"]["left_ee_pose"][0] = 0.051
            return {
                "rejected": True,
                "code": "eef_target_limit",
                "native_step_before": 2,
                "native_step_after": 2,
                "status": {"step": 2, "step_limit": None},
            }
        controls.append(copy.deepcopy(value))
        return {
            "native_step_before": len(controls) - 1,
            "native_step_after": len(controls),
            "status": {"step": len(controls), "step_limit": None},
        }

    env.step_eef = step
    initial = tool.state.latest_record().step_idx
    response = tool.execute_tool(
        "move_eef", {"observation_step": initial, "target": target(), "steps": 5}
    )
    assert not response.is_error and len(response.images) == 3
    result = response.data["log"]["result"]
    assert result["steps_used"] == 2 and result["cancelled_steps"] == 3
    assert result["replan_required"] and len(result["control_steps"]) == 2
    assert len(calls) == 3 and len(controls) == 2
    revised = target()
    revised["left"]["position"][0] = 0.051
    resumed = tool.execute_tool(
        "move_eef",
        {"observation_step": response.data["step"], "target": revised, "steps": 1},
    )
    assert not resumed.is_error and resumed.data["log"]["result"]["steps_used"] == 1
    assert len(controls) == 3


def test_non_range_errors_remain_errors(toolkit):
    tool, calls = toolkit

    def broken(_):
        raise RuntimeError("physics failed")

    tool._primitives.env.step_eef = broken
    response = tool.execute_tool(
        "move_eef",
        {"observation_step": tool.state.latest_record().step_idx, "target": target()},
    )
    assert response.is_error and "physics failed" in response.data["error"]
    assert calls == []
