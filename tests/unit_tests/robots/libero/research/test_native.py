# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Native RPent execution and research observation contracts."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from robots.libero import toolkit as libero
from robots.libero.research.native import SensorResearchToolkit, _arguments_model
from robots.libero.research.sensors import PROPRIO
from rpent.dashboard.events import NullDashboardEventSink, StepRecordEvent
from rpent.memory import MemoryManager
from rpent.tools import ToolResult


def test_native_dispatch_observations_and_events(
    tmp_path, monkeypatch, fake_single_arm_primitives
):
    from rpent.utils import templates

    monkeypatch.setattr(
        templates, "default_variables", lambda: {"output_dir": str(tmp_path)}
    )
    fake = fake_single_arm_primitives.for_robot(libero.libero_tools.LiberoPrimitives)
    fake.env = SimpleNamespace(truncated=False)
    calls = []

    def pick(self, **kwargs):
        calls.append(kwargs)
        return ToolResult(
            data={
                "success": True,
                "chunks_used": 7,
                "max_chunks": kwargs["max_chunks"],
                "diagnostics": {"hidden": "oracle"},
            }
        )

    fake.pi0_pick = libero.libero_tools.LiberoPrimitives.pi0_pick.with_handler(pick)
    monkeypatch.setattr(libero.libero_tools, "LiberoPrimitives", fake)

    def dump(primitives, state, log):
        log = log or {}
        with state.record_step(
            state={
                **dict.fromkeys(PROPRIO, [0.0, 0.0, 0.0]),
                "object_names": ["oracle"],
            },
            terminated=bool(log),
            command=log.get("command"),
            result=log.get("result"),
            extras={"task_language": "place both cans in the basket"},
        ) as step:
            for camera in ("agentview", "wrist"):
                state.save(
                    f"{camera}.png", np.zeros((256, 256, 3), dtype=np.uint8), step=step
                )
        return state.get(step)

    monkeypatch.setattr(libero.libero_tools, "dump_state", dump)
    events = []
    sink = SimpleNamespace(enabled=True, emit=events.append)
    library = tmp_path / "library.json"
    library.write_text(
        json.dumps(
            [
                {
                    "name": "sensor_probe",
                    "description": "Integration fixture; not a research candidate.",
                    "parameters": {
                        "type": "object",
                        "properties": {"count": {"type": "integer"}},
                        "additionalProperties": False,
                    },
                    "source": "raise RuntimeError('must never import generated code on host')\ndef run(frames, params): return {}",
                }
            ]
        )
    )
    generated_calls = []

    def sandbox_call(definition, params, frames):
        generated_calls.append((definition["name"], params))
        return {"count": params.get("count", len(frames))}

    monkeypatch.setattr(
        "robots.libero.research.native.Sandbox",
        lambda image: SimpleNamespace(run=sandbox_call),
    )
    native = SensorResearchToolkit(
        runtime_kwargs={},
        dashboard_events=sink,
        memory=MemoryManager(tmp_path / "memory"),
        state_output_dir=tmp_path / "state",
        sensor_library=str(library),
        sandbox_image="unused",
    )
    names = {t.name for t in native.list_tools()}
    library.write_text("[]")
    monkeypatch.setattr(native.sensors, "frames", lambda: [])
    assert native.execute_tool("sensor_probe", {}).data == {"count": 0}
    assert generated_calls == [("sensor_probe", {})]
    frozen = next((tmp_path / "state" / "sensor-library").glob("*.json"))
    assert json.loads(frozen.read_text())[0]["name"] == "sensor_probe"
    assert not names & {
        "read_text_file",
        "write_text_file",
        "list_dir",
        "reset",
        "execute_action",
    }
    initial = native.execute_tool("view_env_state", {})
    assert initial.data["instruction"] == "place both cans in the basket"
    assert len(initial.images) == 2 and native.state.latest_step == 0
    assert native.execute_tool("segment", {}).is_error
    assert native.execute_tool("segment", {"prompt": "can", "point": [1, 2]}).is_error
    assert native.execute_tool("pi0_pick", {"prompt": "pick", "max_chunks": 3}).is_error
    assert not calls
    result = native.execute_tool("pi0_pick", {"prompt": "pick"})
    assert calls[0]["max_chunks"] == 24
    assert result.data["execution"]["chunks_used"] == 7
    assert "oracle" not in json.dumps(result.data)
    assert "success" not in json.dumps(result.data)
    assert native.solved()
    assert len([e for e in events if isinstance(e, StepRecordEvent)]) == 2
    assert native.execute_tool("pi0_pick", {"prompt": "again"}).is_error
    assert len(calls) == 1
    assert native.execute_tool("finish", {"status": "success", "summary": "done"}).data[
        "_finish"
    ]
    trace = json.loads((tmp_path / "state" / "sensor-trace.json").read_text())
    assert trace["native_success"] is True
    assert "oracle" not in json.dumps(trace)
    monkeypatch.setattr(
        libero.Toolkit,
        "execute_tool",
        lambda self, name, args: ToolResult(
            data={"error": "oracle", "state_capture_error": "private path"}
        ),
    )
    failed = native.execute_tool("pi0_pick", {"prompt": "probe"})
    assert "oracle" not in json.dumps(failed.data)
    assert native.planner_stop_result["status"] == "failed"
    assert json.loads((tmp_path / "state" / "sensor-trace.json").read_text())["error"]


def test_generated_schema_validates_nested_arguments():
    schema = {
        "type": "object",
        "properties": {
            "region": {"type": "array", "items": {"type": "integer"}, "minItems": 2}
        },
        "required": ["region"],
        "additionalProperties": False,
    }
    model = _arguments_model("Region", schema)
    assert model.model_validate({"region": [1, 2]}).region == [1, 2]
    with pytest.raises(ValueError):
        model.model_validate({"region": ["wrong", 2]})


def test_native_api_does_not_add_file_reader(tmp_path):
    from rpent.planner.api_loop import _HarnessToolkit

    toolkit = SimpleNamespace(planner_tools_only=True, list_tools=lambda: ())
    adapter = _HarnessToolkit(
        toolkit, dashboard_events=NullDashboardEventSink(), no_images=False
    )
    assert "read_image" not in adapter.tools


def test_native_api_stops_on_evaluator_boundary(monkeypatch):
    import asyncio

    from rpent.planner.api_loop import _HarnessToolkit
    from rpent.tools import tool
    from rpent.utils import templates

    monkeypatch.setattr(templates, "default_variables", lambda: {})

    @tool
    def action():
        """Perform one test action."""
        return ToolResult(data={"execution": {"steps_used": 1}})

    stopped = {"_finish": True, "environment_stopped": True, "status": "stopped"}
    toolkit = SimpleNamespace(
        planner_tools_only=True,
        planner_stop_result=stopped,
        list_tools=lambda: [action],
        execute_tool=lambda name, args: action(),
    )
    adapter = _HarnessToolkit(
        toolkit, dashboard_events=NullDashboardEventSink(), no_images=False
    )
    cancelled = []
    context = SimpleNamespace(tool_call_id="one", cancel=lambda: cancelled.append(True))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter.execute("action", {}, context))
    assert cancelled and adapter.finish_result == stopped
    assert "environment_stopped" not in adapter.messages[-1]["content"]


def test_codex_native_restriction_keeps_only_rpent_mcp(tmp_path, monkeypatch):
    import openai_codex

    from rpent.planner.base import PlannerResult
    from rpent.planner.codex import CodexPlanner

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('[mcp_servers.unrelated]\ncommand="do-not-run"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    planner = CodexPlanner(
        output_dir=str(tmp_path),
        repo_root=tmp_path,
        dashboard_events=NullDashboardEventSink(),
    )

    def solve(**kwargs):
        config = planner._build_config("http://127.0.0.1:1234/mcp")
        options = "\n".join(config.config_overrides)
        assert "mcp_servers.rpent.url" in options and "unrelated" not in options
        assert "features.shell_tool=false" in options
        assert config.env["CODEX_HOME"] != str(home)
        assert planner._thread_options["sandbox"] == openai_codex.Sandbox.read_only
        return PlannerResult()

    monkeypatch.setattr(planner, "_solve", solve)
    planner.solve(
        system_prompt="",
        user_message="test",
        toolkit=SimpleNamespace(planner_tools_only=True, list_tools=lambda: []),
        max_turns=1,
    )
    assert planner._repo_root == str(tmp_path)
