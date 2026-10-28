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

"""Offline contracts: no hidden reset, truthful feedback, server-gated motion."""

from types import SimpleNamespace

import pytest

from robots.flexiv.env_client import FlexivEnvClient
from robots.flexiv.env_server import FlexivEnvFacade
from robots.flexiv.robot_spec import (
    INSPECTION,
    _parse_config,
    get_robot_spec,
    get_toolkit,
)
from robots.flexiv.toolkit import FlexivToolkit


class FakeRPC:
    def __init__(self):
        self.calls = []

    def call(self, method, **kwargs):
        self.calls.append(method)
        return {"robot": "flexiv", "motion_enabled": False}


def test_connect_never_resets_or_moves():
    rpc = FakeRPC()
    client = FlexivEnvClient(rpc)
    assert rpc.calls == ["env.open", "env.get_env_meta"]
    with pytest.raises(RuntimeError, match="operator"):
        client.reset()
    client.close()
    assert rpc.calls == ["env.open", "env.get_env_meta", "env.close"]


def test_server_does_not_register_reset_or_unbounded_actions():
    backend = SimpleNamespace(
        **{
            name: lambda: None
            for name in (
                "open",
                "get_env_meta",
                "get_observation",
                "move_delta",
                "close",
            )
        }
    )
    facade = FlexivEnvFacade(backend)
    assert set(facade._rpc) == {
        "env.open",
        "env.get_env_meta",
        "env.get_observation",
        "env.move_delta",
        "env.close",
    }


def test_inspection_captures_real_state_without_motion_tools(tmp_path, monkeypatch):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    observations, closed = [], []

    def observe():
        observations.append(True)
        return {
            "state": {"tcp_pose": [0.4, 0.1, -0.3, 1, 0, 0, 0]},
            "images_jpeg": {},
            "native_success": None,
        }

    env = SimpleNamespace(
        meta={"motion_enabled": False},
        get_observation=observe,
        close=lambda: closed.append(True),
    )
    toolkit = FlexivToolkit(
        env=env,
        output_dir=tmp_path,
        dashboard_events=SimpleNamespace(enabled=False, emit=lambda e: None),
        memory=SimpleNamespace(),
    )
    assert [tool.name for tool in toolkit.list_tools()] == ["observe"]
    result = toolkit.execute_tool("observe", {})
    assert result.data["state"]["tcp_pose"][2] == -0.3
    assert result.data["native_success"] is None
    assert not result.images
    assert len(observations) == 2
    toolkit.close()
    assert closed == [True]


def test_robot_registration_and_prompt(tmp_path):
    spec = get_robot_spec()
    assert spec.is_real_robot
    config = _parse_config(
        SimpleNamespace(instruction=INSPECTION, output_dir=str(tmp_path))
    )
    prompt = spec.prompts.render("system", variables=config.prompt_vars)
    assert "side mounted" in prompt
    assert "no camera-to-base calibration" in prompt
    assert config.task_desc["instruction"] == INSPECTION


def test_public_toolkit_factory(tmp_path, monkeypatch):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    config = _parse_config(
        SimpleNamespace(instruction=INSPECTION, output_dir=str(tmp_path))
    )
    env = SimpleNamespace(
        meta={"motion_enabled": False},
        get_observation=lambda: {"state": {"connected": True}, "images_jpeg": {}},
        close=lambda: None,
    )
    toolkit = get_toolkit(
        runtime_kwargs={"env": env},
        config=config,
        dashboard_events=SimpleNamespace(enabled=False, emit=lambda e: None),
    )
    assert "observe" in {t.name for t in toolkit.list_tools()}
    assert "move_delta" not in {t.name for t in toolkit.list_tools()}
    toolkit.close()


def test_freeform_task_instruction_preserves_spaces():
    from robots.flexiv.robot_spec import DASHBOARD_SPEC
    from rpent.dashboard.state import _parse_task

    assert _parse_task(
        DASHBOARD_SPEC["task"], '/rpent-task "Open gripper to 98 mm"'
    ) == {"instruction": "Open gripper to 98 mm"}


def test_motion_publishes_one_frame_event(tmp_path, monkeypatch):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    events = []
    env = SimpleNamespace(
        meta={"motion_enabled": True, "supervised_control": True},
        get_observation=lambda: {
            "state": {"tcp_pose": [0.4, 0, 0.2, 1, 0, 0, 0]},
            "images_jpeg": {},
        },
        set_gripper=lambda width_m: {"reached": True},
        close=lambda: None,
    )
    toolkit = FlexivToolkit(
        env=env,
        output_dir=tmp_path,
        dashboard_events=SimpleNamespace(enabled=True, emit=events.append),
        memory=SimpleNamespace(),
    )
    names = {t.name for t in toolkit.list_tools()}
    assert {"move_tcp", "align_tool_down", "set_gripper", "stop_motion"} <= names
    assert not any("arm" in name or "resume" in name for name in names)
    events.clear()
    toolkit.execute_tool("set_gripper", {"width_m": 0.098})
    assert len(events) == 1
    toolkit.close()


@pytest.mark.parametrize(
    "enabled,failure", [(False, False), (True, False), (True, True)]
)
def test_startup_home_once_only_for_armed_experiment(
    tmp_path, monkeypatch, enabled, failure
):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    calls = []

    def home():
        calls.append("home")
        if failure:
            raise RuntimeError("Home could not reach target")
        return {"reached": True, "joint_error_rad": 0.0}

    env = SimpleNamespace(
        meta={
            "motion_enabled": enabled,
            "supervised_control": True,
            "home_available": True,
            "reset_before_task": True,
        },
        get_observation=lambda: {"state": {}, "images_jpeg": {}},
        reset_home=home,
        close=lambda: calls.append("close"),
    )

    def create():
        return FlexivToolkit(
            env=env,
            output_dir=tmp_path,
            dashboard_events=SimpleNamespace(enabled=False, emit=lambda e: None),
            memory=SimpleNamespace(),
        )

    if failure:
        with pytest.raises(RuntimeError, match="startup home failed"):
            create()
        assert calls == ["home", "close"]
    else:
        kit = create()
        kit.execute_tool("observe", {})
        assert calls == (["home"] if enabled else [])
        kit.close()


def test_cancelling_active_motion_requests_stop_before_waiting(tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    entered, stopped = threading.Event(), threading.Event()

    def move(*args):
        entered.set()
        assert stopped.wait(2)
        return {"stopped": True}

    env = SimpleNamespace(
        meta={"motion_enabled": True, "supervised_control": True},
        get_observation=lambda: {"state": {}, "images_jpeg": {}},
        move_tcp=move,
        stop_motion=lambda: stopped.set(),
        close=lambda: None,
    )
    toolkit = FlexivToolkit(
        env=env,
        output_dir=tmp_path,
        dashboard_events=SimpleNamespace(enabled=False, emit=lambda e: None),
        memory=SimpleNamespace(),
    )
    worker = threading.Thread(
        target=lambda: toolkit.execute_tool("move_tcp", {"position_m": [0.4, 0.0, 0.2]})
    )
    worker.start()
    try:
        assert entered.wait(1)
        toolkit.cancel_active_and_wait()
        assert stopped.is_set()
    finally:
        stopped.set()
        worker.join(2)
        toolkit.close()
    assert not worker.is_alive()


def test_short_eef_rpc_is_explicit_and_preserves_field_names():
    rpc = FakeRPC()
    client = FlexivEnvClient(rpc)
    calls = []
    rpc.call = lambda method, **kwargs: calls.append((method, kwargs)) or {"held": True}
    assert client.move_eef([0.4, 0, 0.2], [1, 0, 0, 0], 5)["held"]
    assert calls == [
        (
            "env.move_eef",
            {
                "kwargs": {
                    "position_m": [0.4, 0, 0.2],
                    "quaternion_wxyz": [1, 0, 0, 0],
                    "steps": 5,
                },
                "timeout_s": 40,
            },
        )
    ]


def test_prompt_uses_measured_tcp_and_real_command_fields(tmp_path):
    from robots.flexiv.prompt_bundle import system_prompt

    config = _parse_config(
        SimpleNamespace(
            instruction="Insert the USB drive",
            output_dir=str(tmp_path),
            control_mode="eef_delta",
        )
    )
    assert config.task_desc["control_mode"] == "eef_delta"
    prompt = system_prompt(config.prompt_vars)
    assert (
        prompt["POLICY"]
        == "Operate as the autonomous policy for one physical Flexiv episode."
    )
    assert (
        prompt["EMBODIMENT"]
        == "Robot: one Flexiv Rizon4 arm with one gripper. Views are side and wrist RGB-D."
    )
    text = get_robot_spec().prompts.render("system", variables=config.prompt_vars)
    assert "state.tcp_pose" in text
    assert "translation_m" in text and "rotation_vector_rad" in text
    assert "width_m" in text and "wxyz" in text
    assert "25 Hz" in text
    assert "not repeated increments" in text
    assert "localization is not a prerequisite" in text
    native = get_robot_spec().prompts.render("system", variables={})
    assert native == get_robot_spec().prompts.render(
        "system", variables={"control_mode": "native"}
    )
    assert "move_eef_delta" not in native


def test_eef_endpoint_registered_only_with_explicit_capability():
    from robots.flexiv.env_server import CollectorBackend

    backend = CollectorBackend("http://unused", supervised=True)
    assert "env.move_eef" not in FlexivEnvFacade(backend)._rpc
    assert "env.move_eef_delta" not in FlexivEnvFacade(backend)._rpc
    backend.eef_chunk_control = True
    assert "env.move_eef" in FlexivEnvFacade(backend)._rpc
    assert "env.move_eef_delta" in FlexivEnvFacade(backend)._rpc
    backend.supervised = False
    assert "env.move_eef_delta" not in FlexivEnvFacade(backend)._rpc


@pytest.mark.parametrize("enabled", [False, True])
def test_eef_tool_capability_and_strict_steps(tmp_path, monkeypatch, enabled):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    calls = []
    env = SimpleNamespace(
        meta={
            "motion_enabled": True,
            "supervised_control": True,
            "eef_chunk_control": enabled,
        },
        get_observation=lambda: {
            "state": {"tcp_pose": [0.4, 0, 0.2, 1, 0, 0, 0]},
            "images_jpeg": {},
        },
        move_eef=lambda *args: calls.append(args) or {"held": True},
        close=lambda: None,
    )
    kit = FlexivToolkit(
        env=env,
        output_dir=tmp_path,
        memory=SimpleNamespace(),
        dashboard_events=SimpleNamespace(enabled=False, emit=lambda e: None),
    )
    declarations = {tool.name: tool for tool in kit.list_tools()}
    assert ("move_eef" in declarations) is enabled
    if enabled:
        assert set(declarations["move_eef"].input_schema["required"]) == {
            "position_m",
            "quaternion_wxyz",
            "steps",
        }
        arguments = {
            "position_m": [0.41, 0, 0.2],
            "quaternion_wxyz": [1, 0, 0, 0],
            "steps": True,
        }
        assert kit.execute_tool("move_eef", arguments).is_error
        assert calls == []
        arguments["steps"] = 5
        assert not kit.execute_tool("move_eef", arguments).is_error
        assert calls == [([0.41, 0, 0.2], [1, 0, 0, 0], 5)]
    kit.close()


def test_incremental_eef_client_preserves_fields_and_timeout():
    rpc = FakeRPC()
    client = FlexivEnvClient(rpc)
    calls = []
    rpc.call = lambda method, **kwargs: calls.append((method, kwargs)) or {"held": True}
    assert client.move_eef_delta([0.001, 0, 0], [0, 0.01, 0], 3)["held"]
    assert calls == [
        (
            "env.move_eef_delta",
            {
                "kwargs": {
                    "translation_m": [0.001, 0, 0],
                    "rotation_vector_rad": [0, 0.01, 0],
                    "steps": 3,
                },
                "timeout_s": 40,
            },
        )
    ]


def test_eef_mode_factory_whitelist_and_post_action_capture(tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image

    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    events, calls, captures = [], [], []
    picture = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(picture, format="PNG")
    image = base64.b64encode(picture.getvalue()).decode()
    pose = [0.4, 0, 0.2, 1, 0, 0, 0]

    def observe():
        captures.append(True)
        return {"state": {"tcp_pose": list(pose)}, "images_png": {"wrist": image}}

    def move(*args):
        calls.append(args)
        pose[0] += 0.001
        return {"held": True, "reached": False, "measured_pose": list(pose)}

    env = SimpleNamespace(
        meta={
            "motion_enabled": True,
            "supervised_control": True,
            "eef_chunk_control": True,
            "home_available": True,
        },
        get_observation=observe,
        move_eef_delta=move,
        close=lambda: None,
    )
    config = _parse_config(
        SimpleNamespace(
            instruction="Insert the USB drive",
            output_dir=str(tmp_path),
            control_mode="eef_delta",
        )
    )
    kit = get_toolkit(
        runtime_kwargs={"env": env},
        config=config,
        dashboard_events=SimpleNamespace(enabled=True, emit=events.append),
    )
    declarations = {tool.name: tool for tool in kit.list_tools()}
    assert set(declarations) == {
        "observe",
        "move_eef_delta",
        "set_gripper",
        "stop_motion",
    }
    assert set(declarations["move_eef_delta"].input_schema["required"]) == {
        "translation_m",
        "rotation_vector_rad",
        "steps",
    }
    arguments = {
        "translation_m": [0.01, 0, 0],
        "rotation_vector_rad": [0, 0, 0],
        "steps": True,
    }
    assert kit.execute_tool("move_eef_delta", arguments).is_error
    assert kit.execute_tool("move_tcp", {"position_m": pose[:3]}).is_error
    assert not calls and len(captures) == 1
    events.clear()
    arguments["steps"] = 5
    result = kit.execute_tool("move_eef_delta", arguments)
    assert not result.is_error and len(result.images) == 1
    assert calls == [([0.01, 0, 0], [0, 0, 0], 5)]
    assert len(captures) == 2 and len(events) == 1
    assert result.data["state"]["tcp_pose"] == pose
    assert result.data["action_result"]["held"]
    assert not result.data["action_result"]["reached"]
    record = kit.state.latest_record()
    assert record.command == {"action": "move_eef_delta", **arguments}
    assert record.state["tcp_pose"] == pose
    assert "wrist.png" in record.artifacts
    kit.close()


@pytest.mark.parametrize(
    "failure",
    ["mode", "motion_enabled", "supervised_control", "eef_chunk_control", "reset"],
)
def test_eef_mode_rejects_unavailable_configuration_before_observation(
    tmp_path, monkeypatch, failure
):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    calls = []
    meta = {
        "motion_enabled": True,
        "supervised_control": True,
        "eef_chunk_control": True,
    }
    if failure in meta:
        meta[failure] = False
    if failure == "reset":
        meta["reset_before_task"] = True
    env = SimpleNamespace(
        meta=meta,
        get_observation=lambda: calls.append("observe"),
        reset_home=lambda: calls.append("home"),
        close=lambda: calls.append("close"),
    )
    with pytest.raises(ValueError):
        FlexivToolkit(
            env=env,
            output_dir=tmp_path,
            control_mode="unknown" if failure == "mode" else "eef_delta",
            memory=SimpleNamespace(),
            dashboard_events=SimpleNamespace(enabled=False, emit=lambda e: None),
        )
    assert not calls
