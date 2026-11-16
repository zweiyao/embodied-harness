# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Workbench choices preserve native RoboDojo identities and execution limits."""

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from robots.robodojo import native_catalog
from robots.robodojo.catalog import task_fields
from robots.robodojo.robot_spec import ROBODOJO_DASHBOARD_SPEC
from robots.robodojo.toolkit import RoboDojoToolkit
from rpent.dashboard.events import NullDashboardEventSink
from rpent.dashboard.server import DashboardServer
from rpent.dashboard.state import DashboardState
from rpent.dashboard.workbench import RunJournal, Workbench
from rpent.memory import MemoryManager
from rpent.tools import iter_tools
from rpent.tools.common import CommonTools


def selected(*names):
    return [t for t in native_catalog() if t["name"] in names]


def test_catalog_is_read_only_and_preserves_native_schemas(monkeypatch):
    from robots.robodojo import tools

    monkeypatch.setattr(
        RoboDojoToolkit, "__init__", lambda *a, **k: pytest.fail("No ENV")
    )
    declarations = {t.name: t for t in [*iter_tools(tools), *iter_tools(CommonTools)]}
    catalog = native_catalog()
    assert {t["name"] for t in catalog} == set(declarations)
    for item in catalog:
        assert item["parameters"] == declarations[item["name"]].input_schema
        assert item["description"] == declarations[item["name"]].description
    assert [t["name"] for t in catalog if t["required"]] == ["finish"]


@pytest.mark.parametrize(
    "change", ["version", "source", "parameters", "description", "generated"]
)
def test_stale_and_unsupported_tools_rejected_before_environment(change, tmp_path):
    frozen = copy.deepcopy(selected("finish", "view_env_state"))
    frozen[1]["origin" if change == "generated" else change] = "changed"
    with pytest.raises(ValueError):
        RoboDojoToolkit(
            primitives_kwargs={},
            dashboard_events=NullDashboardEventSink(),
            memory=MemoryManager(tmp_path / "memory"),
            selected=frozen,
        )
    assert not (tmp_path / "states.json").exists()


def test_allowlist_is_enforced_and_actual_calls_are_journaled(monkeypatch, tmp_path):
    from rpent.utils import logging

    monkeypatch.setattr(logging, "_output_dir", tmp_path)
    env = SimpleNamespace(
        get_obs=lambda: {"vision": {}, "state": {}},
        get_status=lambda: {"step": 0, "step_limit": 10},
        get_task_language=lambda: "Pick the bottle.",
    )
    toolkit = RoboDojoToolkit(
        primitives_kwargs={"env": env},
        dashboard_events=NullDashboardEventSink(),
        memory=MemoryManager(tmp_path / "memory"),
        selected=selected("finish", "view_env_state"),
        journal=RunJournal(tmp_path),
    )
    assert {t.name for t in toolkit.list_tools()} == {"finish", "view_env_state"}
    assert toolkit.planner_tools_only is True
    observed = toolkit.execute_tool("view_env_state", {})
    assert observed.data["task_language"] == "Pick the bottle."
    assert "unknown tool" in toolkit.execute_tool("move_to", {}).data["error"]
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
    ]
    requests = [e["payload"] for e in events if e["kind"] == "tool_request"]
    responses = [e["payload"] for e in events if e["kind"] == "tool_response"]
    assert [r["name"] for r in requests] == ["view_env_state", "move_to"]
    assert [r["call_id"] for r in requests] == [r["call_id"] for r in responses]
    assert responses[1]["result"]["error"]
    toolkit.close()


def test_native_layout_ids_are_enumeration_positions_in_configured_group(tmp_path):
    source, assets = tmp_path / "source", tmp_path / "data"
    (source / "env_cfg").mkdir(parents=True)
    (source / "env_cfg/arx_x5.yml").write_text("config_name: arx_x5\n")
    configs = source / "task/RoboDojo/config"
    configs.mkdir(parents=True)
    for name in ["task_a", "task_b", "_task"]:
        (configs / f"{name}.yml").write_text("{}")
    layouts = assets / "Assets/Eval_Layout/RoboDojo/arx_x5/0"
    layouts.mkdir(parents=True)
    for name in ["task_a_90", "task_a_3", "task_a_2_bad", "task_b_100"]:
        (layouts / f"{name}.json").write_text("{}")
    fields = task_fields(source, assets)
    assert fields[0]["options"] == [["task_a", "task_a"], ["task_b", "task_b"]]
    assert fields[1]["options_by"] == {
        "task_a": [[0, "0"], [1, "1"]],
        "task_b": [[0, "0"]],
    }
    (layouts / "task_b_100.json").unlink()
    with pytest.raises(ValueError, match="No fixed layouts.*task_b"):
        task_fields(source, assets)


def test_server_exposes_native_command_and_rejects_unknown_layout(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RPENT_TOOL_CATALOG", raising=False)
    monkeypatch.delenv("RPENT_DASHBOARD_SETUP", raising=False)
    fields = [
        {"name": "task", "label": "Task", "options": [["task_a", "task_a"]]},
        {
            "name": "layout",
            "label": "Layout",
            "depends_on": "task",
            "options_by": {"task_a": [[0, "0"], [1, "1"]]},
        },
    ]
    bench = Workbench(
        {
            "robot": "robodojo",
            "runs_root": str(tmp_path),
            "library_root": str(tmp_path / "library"),
            "models": [{"id": "fixture", "planner": "api", "model": "fixture"}],
            "setup": {"profiles": [{"robot": "robodojo", "task_fields": fields}]},
        },
        robot="robodojo",
    )
    bench.checks["fixture"] = {"ok": True}
    state = DashboardState(
        output_dir=tmp_path / "session", dashboard_spec=ROBODOJO_DASHBOARD_SPEC
    )
    state.workbench = bench
    state.shared_services_ready()
    server = DashboardServer(state=state, robot_name="robodojo")
    client = TestClient(server._app)
    setup = client.get("/api/setup").json()
    assert [f["name"] for f in setup["task_spec"]["fields"]] == ["task", "layout"]
    assert setup["workbench"] is True
    assert client.get("/").status_code == 200
    assert client.get("/api/tools").status_code == 200
    with pytest.raises(ValueError, match="Unsupported task field layout"):
        state.submit_input("/rpent-task task_a 2")
    assert state.submit_input("/rpent-task task_a 1")["layout"] == 1
    claimed = state.wait_for_task(0)
    assert claimed.request["task"] == "task_a"
    assert claimed.request["layout"] == 1
    assert "suite" not in claimed.request and "seed" not in claimed.request


def test_dashboard_loads_robot_owned_workbench_without_starting_tasks(
    tmp_path, monkeypatch
):
    import argparse
    from dataclasses import replace

    from robots.robodojo.robot_spec import get_robot_spec
    from rpent.cli import dashboard
    from rpent.cli.main import _build_argparser

    path = tmp_path / "workbench.json"
    path.write_text(
        json.dumps(
            {
                "robot": "robodojo",
                "runs_root": str(tmp_path),
                "library_root": str(tmp_path / "library"),
                "setup": {},
                "models": [{"id": "fixture", "planner": "codex", "model": "fixture"}],
            }
        )
    )
    monkeypatch.setenv("RPENT_WORKBENCH", str(path))
    monkeypatch.delenv("RPENT_TOOL_CATALOG", raising=False)
    monkeypatch.delenv("RPENT_DASHBOARD_SETUP", raising=False)
    calls = []

    def runtime(args, output_dir, state, components):
        calls.append(components)
        assert components == {"vla", "sam3"}
        return [], {}

    def start(server):
        assert server._workbench.robot == "robodojo"
        assert "native:move_to" in server._planner_config["tools"]
        server._state.request_shutdown()
        return "http://127.0.0.1:12345"

    spec = replace(get_robot_spec(), init_runtime=runtime)
    parser = _build_argparser()
    spec.add_cli_args(parser, use_dashboard=True)
    args = parser.parse_args(
        [
            "--robot",
            "robodojo",
            "--dashboard",
            "--planner",
            "codex",
            "--model",
            "fixture",
            "--memory-profile",
            "local",
            "--memory-dir",
            str(tmp_path / "memory"),
            "--output-dir",
            str(tmp_path / "session"),
        ]
    )
    monkeypatch.setattr(DashboardServer, "start", start)
    assert (
        dashboard.run_dashboard_session(args, spec, parser=argparse.ArgumentParser())
        == 0
    )
    assert calls == [{"vla", "sam3"}]
