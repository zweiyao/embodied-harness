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

"""Direct RDK declarations, dispatch and runtime selection without hardware."""

import argparse
from types import SimpleNamespace

import pytest

from robots.flexiv import robot_spec
from robots.flexiv.toolkit import FlexivToolkit


def make_env(calls, **metadata):
    def action(name):
        return lambda *args: calls.append((name, args)) or {"reached": True}

    return SimpleNamespace(
        meta={"control_backend": "rdk", "motion_enabled": True, **metadata},
        get_observation=lambda: {
            "state": {"tcp_pose": [0.4, 0.0, 0.2, 1.0, 0.0, 0.0, 0.0]},
            "images_jpeg": {},
            "control_limits": {"linear_velocity_m_s": 0.05},
        },
        move_tcp=action("move_tcp"),
        move_eef_delta=action("move_eef_delta"),
        set_gripper=action("set_gripper"),
        stop_motion=action("stop_motion"),
        close=lambda: calls.append(("close", ())),
    )


@pytest.fixture
def toolkit_factory(tmp_path, monkeypatch):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)

    def create(env, control_mode="rdk"):
        return FlexivToolkit(
            env=env,
            output_dir=tmp_path,
            control_mode=control_mode,
            memory=SimpleNamespace(),
            dashboard_events=SimpleNamespace(enabled=False, emit=lambda event: None),
        )

    return create


def test_rdk_declarations_dispatch_without_collector_or_steps(toolkit_factory):
    calls = []
    kit = toolkit_factory(make_env(calls))
    try:
        tools = {item.name: item for item in kit.list_tools()}
        assert set(tools) == {
            "observe",
            "move_tcp",
            "move_eef_delta",
            "set_gripper",
            "stop_motion",
        }
        assert set(tools["move_eef_delta"].input_schema["properties"]) == {
            "translation_m",
            "rotation_vector_rad",
        }
        delta = {"translation_m": [0.02, 0, 0], "rotation_vector_rad": [0, 0, 0]}
        assert kit.execute_tool("move_eef_delta", {**delta, "steps": 5}).is_error
        assert not calls
        result = kit.execute_tool("move_eef_delta", delta)
        assert not result.is_error
        assert calls == [("move_eef_delta", ([0.02, 0, 0], [0, 0, 0]))]
        assert result.data["action_result"]["reached"]
        assert result.data["control_limits"]["linear_velocity_m_s"] == 0.05
        assert kit.state.latest_record().command == {
            "action": "move_eef_delta",
            **delta,
        }
        assert not kit.execute_tool("move_tcp", {"position_m": [0.4, 0, 0.25]}).is_error
        assert calls[-1] == ("move_tcp", ([0.4, 0, 0.25], None))
        assert not kit.execute_tool("set_gripper", {"width_m": 0.05}).is_error
        assert calls[-1] == ("set_gripper", (0.05,))
        before = list(calls)
        for unavailable in ("move_delta", "move_eef", "reset_home", "activate_gripper"):
            assert kit.execute_tool(unavailable, {}).is_error
        assert calls == before
    finally:
        kit.close()


def test_rdk_readonly_does_not_expose_actions(toolkit_factory):
    kit = toolkit_factory(make_env([], motion_enabled=False))
    try:
        assert [item.name for item in kit.list_tools()] == ["observe"]
    finally:
        kit.close()


@pytest.mark.parametrize(
    "metadata,mode",
    [
        ({"control_backend": "collector"}, "rdk"),
        ({}, "native"),
        ({}, "eef_delta"),
        ({"motion_enabled": "true"}, "rdk"),
        ({"reset_before_task": True}, "rdk"),
    ],
)
def test_rdk_rejects_backend_mode_mismatch_before_observation(
    toolkit_factory, metadata, mode
):
    env = make_env([], **metadata)
    env.get_observation = lambda: pytest.fail("Invalid config must not capture")
    with pytest.raises(ValueError):
        toolkit_factory(env, mode)


def test_rdk_cli_and_prompt_keep_arrival_semantics(tmp_path):
    parser = argparse.ArgumentParser()
    robot_spec._add_cli_args(parser, use_dashboard=True)
    args = parser.parse_args(
        ["--control-mode", "rdk", "--rdk-endpoint", "http://robot:5000"]
    )
    args.output_dir = str(tmp_path)
    config = robot_spec._parse_config(args)
    assert config.task_desc["control_mode"] == "rdk"
    assert args.rdk_endpoint == "http://robot:5000"
    prompt = robot_spec.get_robot_spec().prompts.render(
        "system", variables=config.prompt_vars
    )
    assert "until arrival or the command deadline" in prompt
    assert "rotation_vector_rad" in prompt and "wxyz" in prompt
    assert "control_limits" in prompt
    assert "25 Hz" not in prompt and "steps" not in prompt
    assert "collector" not in prompt.lower()


def test_rdk_runtime_spawns_direct_backend_without_collector(tmp_path, monkeypatch):
    commands = []

    class Daemon:
        def __init__(self, **kwargs):
            commands.append(kwargs["cmd"])

        def start(self):
            pass

    monkeypatch.setattr(robot_spec, "ProcessDaemon", Daemon)
    monkeypatch.setattr(robot_spec, "pick_free_port", lambda: 9123)
    monkeypatch.setattr(
        robot_spec, "try_spawn_server", lambda owned, events, name, spawn: spawn()
    )
    monkeypatch.setattr(robot_spec, "try_wait_server", lambda *args, **kwargs: "env")
    args = SimpleNamespace(
        env_endpoint=None, control_mode="rdk", rdk_endpoint="http://robot:5000"
    )
    _, runtime = robot_spec._init_runtime(args, tmp_path, None)
    assert runtime == {"env": "env"}
    command = commands[0]
    assert command[command.index("--backend") + 1] == "rdk"
    assert command[command.index("--rdk-endpoint") + 1] == args.rdk_endpoint
    assert "--collector-endpoint" not in command
