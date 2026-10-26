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
