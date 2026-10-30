# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Robot hooks use real pilot accounting, tool persistence and maker exports."""

import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from robots.univtac import robot_spec, toolkit
from robots.univtac.pilot import Pilot
from robots.univtac.pilot.execution import restore_from_output
from rpent.dashboard.events import NullDashboardEventSink
from tests.unit_tests.robots.univtac.test_execution import (
    evidence,
    freeze_after_development,
    profile,
    scene,
)
from tests.unit_tests.robots.univtac.test_toolkit import POSE, FakeEnv


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    monkeypatch.setattr("rpent.utils.templates.get_output_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "robots.univtac.pilot.provenance.collect", lambda: copy.deepcopy(evidence())
    )
    monkeypatch.setattr(
        "rpent.dashboard.workbench.source_snapshot",
        lambda *args: {"revision": "offline-test", "files": {}},
    )
    return Pilot.create(tmp_path / "pilot")


def prepare(pilot, output, cell_id="dev-03", freeze=None, **profile_overrides):
    cell = pilot._cell(cell_id)
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(output))
    robot_spec._add_cli_args(parser, use_dashboard=False)
    parser.set_defaults(**{**profile(cell["model"]), **profile_overrides})
    args = parser.parse_args(
        [
            "--pilot-root",
            str(pilot.root),
            "--pilot-cell",
            cell_id,
            "--seed",
            str(cell["seed"]),
            "--univtac-root",
            "/offline-benchmark",
            "--univtac-python",
            "/offline-python",
        ]
        + (["--pilot-freeze", freeze] if freeze else [])
    )
    robot_spec._validate_args(args)
    config = robot_spec._parse_config(args)
    if cell["stage"] == "provisional":
        config.prompt_vars["manual_tools"] = toolkit.native_catalog()
    robot_spec._prepare_memory(args, config)
    return args, config


@pytest.mark.parametrize("cell_id", ["dev-03", "dev-05"])
def test_new_model_runs_record_and_apply_300_second_waits(pilot, tmp_path, cell_id):
    from rpent.planner.request_timeout import request_timeout

    args, config = prepare(
        pilot, tmp_path / cell_id, cell_id, max_tokens=10000, reasoning_effort="low"
    )
    api = robot_spec.get_toolkit(
        runtime_kwargs={"env": FakeEnv()},
        dashboard_events=NullDashboardEventSink(),
        config=config,
    )
    try:
        manifest = json.loads((config.output_dir / "manifest.json").read_text())
        recorded = restore_from_output(config.output_dir).record
        assert (
            manifest["budget"]
            == recorded["budget"]
            == {
                "max_turns": 60,
                "planner_timeout_s": 3600,
                "model_request_timeout_s": 300,
            }
        )
        assert request_timeout(api) == 300
        assert recorded["model_profile_settings"]["planner"] == args.planner
        assert manifest["profile"]["max_tokens"] == 10000
        assert manifest["profile"]["reasoning_effort"] == "low"
    finally:
        api.close()


def test_frozen_prepare_applies_guidance_selection_and_resolved_sandbox_id(
    pilot, tmp_path, monkeypatch
):
    frozen, bundle = freeze_after_development(pilot, tmp_path)
    _, config = prepare(pilot, tmp_path / "frozen-run", "dev-07", frozen)
    assert pilot.summary()["episodes_reserved"] == 7
    assert pilot.summary()["finished"] == 6
    execution = restore_from_output(config.output_dir)
    assert execution.record["freeze_id"] == frozen
    assert config.prompt_vars["manual_tools"] == bundle["conditions"]["E"]["tools"]
    assert config.prompt_vars["task_guidance"] == bundle["conditions"]["E"]["guidance"]
    assert (
        config.prompt_vars["sandbox_image"] == evidence()["controller"]["sandbox_image"]
    )
    prompts = json.loads((config.output_dir / "prompts.json").read_text())
    assert bundle["conditions"]["E"]["guidance"] in prompts["user"]

    class ImageOnlySandbox:
        def __init__(self, image):
            self.image = image

    monkeypatch.setattr(toolkit, "Sandbox", ImageOnlySandbox)
    api = robot_spec.get_toolkit(
        runtime_kwargs={"env": FakeEnv()},
        dashboard_events=NullDashboardEventSink(),
        config=config,
    )
    try:
        assert api.sandbox.image == evidence()["controller"]["sandbox_image"]
        assert {t.name for t in api.list_tools()} == {
            t["name"] for t in bundle["conditions"]["E"]["tools"]
        }
        with pytest.raises(PermissionError):
            api.memory.authorize_write(api.memory.root / "MEMORY.md")
    finally:
        api.close()


@pytest.mark.parametrize("phase", ["spawn", "reset"])
def test_startup_failure_keeps_pre_reset_charge_and_finishes_setup_failure(
    pilot, tmp_path, monkeypatch, phase
):
    args, config = prepare(pilot, tmp_path / "failed-run")
    lifecycle = []

    def reserved():
        assert pilot.summary()["episodes_reserved"] == 1
        assert restore_from_output(config.output_dir).record["cell"]["id"] == "dev-03"

    class Daemon:
        def __init__(self, **kwargs):
            pass

        def start(self):
            reserved()
            lifecycle.append("spawn")
            if phase == "spawn":
                raise RuntimeError("simulator unavailable")

        def stop(self):
            lifecycle.append("stop")

    class Rpc:
        def call(self, name, **kwargs):
            if name == "env.get_env_meta":
                return {"robot": "univtac", "task_name": "insert_hole"}
            assert name == "env.reset"
            reserved()
            lifecycle.append("reset")
            raise RuntimeError("simulator unavailable")

    monkeypatch.setattr(robot_spec, "ProcessDaemon", Daemon)
    monkeypatch.setattr(robot_spec, "pick_free_port", lambda: 18760)
    monkeypatch.setattr(robot_spec, "HttpRpcClient", lambda endpoint: Rpc())
    monkeypatch.setattr(
        "rpent.robots.runtime.wait_for_ready", lambda *args, **kwargs: None
    )
    with pytest.raises(RuntimeError, match="simulator unavailable"):
        robot_spec._init_runtime(args, config.output_dir, NullDashboardEventSink())
    summary = pilot.summary()
    assert summary["episodes_reserved"] == summary["finished"] == 1
    assert summary["rows"][0]["termination_reason"] == "setup_failure"
    assert summary["rows"][0]["native_success"] is None
    assert ("reset" in lifecycle) is (phase == "reset")
    assert phase != "reset" or "stop" in lifecycle
    outcome = json.loads((config.output_dir / "outcome.json").read_text())
    assert outcome["termination_reason"] == "setup_failure"
    with pytest.raises(ValueError, match="already been used"):
        pilot.reserve_episode("dev-03", "a-retry-must-not-be-free")


def test_pilot_rejects_borrowed_environment_before_reserving(pilot, tmp_path):
    args = SimpleNamespace(
        env_endpoint="http://127.0.0.1:18760",
        univtac_root=None,
        univtac_python=None,
        pilot_root=str(pilot.root),
        pilot_cell="dev-03",
        pilot_freeze=None,
    )
    with pytest.raises(ValueError, match="owned fresh simulator"):
        robot_spec._validate_args(args)
    assert pilot.summary()["episodes_reserved"] == 0


def test_prepare_manifest_write_failure_closes_reserved_attempt(
    pilot, tmp_path, monkeypatch
):
    from rpent.dashboard import workbench

    original_write = workbench.write_json

    def write_json(path, value):
        if Path(path).name == "manifest.json":
            raise OSError("manifest write failed")
        return original_write(path, value)

    monkeypatch.setattr(workbench, "write_json", write_json)
    with pytest.raises(OSError, match="manifest write failed"):
        prepare(pilot, tmp_path / "write-failed")
    summary = pilot.summary()
    assert summary["episodes_reserved"] == summary["finished"] == 1
    assert summary["rows"][0]["termination_reason"] == "setup_failure"
    assert "manifest write failed" in summary["rows"][0]["error"]
    assert (
        json.loads((tmp_path / "write-failed" / "outcome.json").read_text())[
            "termination_reason"
        ]
        == "setup_failure"
    )


@pytest.mark.parametrize("saved_status", [None, "network_failure"])
def test_workbench_restart_finishes_active_ledger_without_refunding(
    pilot, tmp_path, saved_status
):
    from rpent.dashboard.workbench import Workbench

    runs = tmp_path / "runs"
    output = runs / "session" / "tasks" / "interrupted"
    prepare(pilot, output)
    if saved_status is not None:
        (output / "outcome.json").write_text(
            json.dumps(
                {
                    "status": saved_status,
                    "environment_success": None,
                    "error": "connection lost after outcome write",
                }
            )
        )
    workbench = Workbench(
        {
            "robot": "univtac",
            "runs_root": str(runs),
            "library_root": str(tmp_path / "library"),
            "models": [],
        },
        robot="univtac",
    )
    workbench.recover_interrupted()
    workbench.recover_interrupted()
    summary = pilot.summary()
    assert summary["episodes_reserved"] == summary["finished"] == 1
    assert summary["rows"][0]["termination_reason"] == (saved_status or "abnormal_exit")
    assert summary["rows"][0]["native_success"] is None
    assert restore_from_output(output).record["outcome"]["termination_reason"] == (
        saved_status or "abnormal_exit"
    )


@pytest.mark.parametrize("cell_id,official", [("dev-03", False), ("dev-05", True)])
def test_finalizer_exports_real_tool_records_into_maker_ledger(
    pilot, tmp_path, cell_id, official
):
    _, config = prepare(pilot, tmp_path / cell_id, cell_id)
    execution = restore_from_output(config.output_dir)
    execution.after_reset({"scene": scene()})
    api = robot_spec.get_toolkit(
        runtime_kwargs={"env": FakeEnv(end_after=1, success=official)},
        dashboard_events=NullDashboardEventSink(),
        config=config,
    )
    try:
        assert not api.execute_tool("move_eef", {"poses": [POSE]}).is_error
        assert api.execute_tool(
            "depth_points", {"camera": "head", "pixels_rc": [[99, 99]]}
        ).is_error
        finish = api.execute_tool(
            "finish",
            {
                "status": "stuck" if official else "success",
                "summary": "model judgment",
            },
        ).data
        context = SimpleNamespace(
            output_dir=config.output_dir,
            environment_success=api.solved(),
            agent_error=None,
            elapsed_s=1.0,
            stats={},
            finish_result=finish,
        )
    finally:
        api.close()
    robot_spec._finalize_run(context)
    row = pilot.summary()["rows"][0]
    assert row["native_success"] is official
    assert row["finish"]["status"] == ("stuck" if official else "success")
    attempt = execution.attempt_id
    g0 = pilot.maker_inputs("G0", [attempt])[0]["files"]
    g1 = pilot.maker_inputs("G1", [attempt])[0]["files"]
    assert set(g0) == {"sensors", "actions"}
    assert ("feedback" in g1) is (cell_id == "dev-05")
    assert all(Path(item["path"]).is_file() for item in g1.values())
    actions = json.loads(Path(g0["actions"]["path"]).read_text())["steps"]
    assert actions[0]["command"] == {"action": "move_eef", "poses": [POSE]}
    with ZipFile(g0["sensors"]["path"]) as archive:
        assert json.loads(archive.read("manifest.json"))["steps"] == [0, 1]
        assert archive.read("frames/0001/sensor_cameras_head_depth.npz")
    if "feedback" in g1:
        calls = json.loads(Path(g1["feedback"]["path"]).read_text())["calls"]
        assert any(
            c["name"] == "depth_points" and c["result"].get("error") for c in calls
        )


@pytest.mark.parametrize("planner_name", ["api", "codex"])
def test_dashboard_archives_selected_prompt_without_legacy_override(
    tmp_path, monkeypatch, planner_name
):
    from dataclasses import replace

    from rpent.cli import dashboard, main
    from rpent.dashboard.state import ClaimedTask, DashboardState
    from rpent.dashboard.workbench import RunJournal
    from rpent.planner.base import PlannerResult

    parser = main._build_argparser()
    robot_spec._add_cli_args(parser, use_dashboard=True)
    args = parser.parse_args(["--robot", "univtac", "--planner", planner_name])
    output = tmp_path / "episode"
    selected = [
        item
        for item in toolkit.native_catalog()
        if item["name"] in {"finish", "observe"}
    ]
    spec = replace(
        robot_spec.get_robot_spec(),
        init_runtime=lambda *args: ([], {"env": FakeEnv()}),
        finalize_run=None,
    )
    state = DashboardState(output_dir=output, dashboard_spec=robot_spec.DASHBOARD_SPEC)
    state.workbench = SimpleNamespace(config={})
    state.journal = RunJournal(output)
    monkeypatch.setattr(main, "get_robot_spec", lambda name: spec)
    monkeypatch.setattr("rpent.dashboard.workbench.source_snapshot", lambda *args: {})
    captured = []

    class Planner:
        def solve(self, **kwargs):
            captured.append(kwargs["system_prompt"])
            assert {t.name for t in kwargs["toolkit"].list_tools()} == {
                "observe",
                "finish",
            }
            return PlannerResult(finish_result=None, messages=[], stats={})

    monkeypatch.setattr(dashboard, "build_planner", lambda *args, **kwargs: Planner())
    error = dashboard._run_dashboard_task_inner(
        args=args,
        robot_spec=spec,
        state=state,
        claimed=ClaimedTask(
            number=1, request={"frozen_tools": selected}, output_dir=output
        ),
        shared_runtime_kwargs={},
        unique_components={"env"},
        session_root=tmp_path,
    )
    assert error is None
    saved = json.loads((output / "prompts.json").read_text())["system"]
    assert captured == [saved]
    assert "AVAILABLE TOOLS" in saved and "observe:" in saved
    assert "EXPERIMENT TOOL SELECTION" not in saved
    assert "move_eef" not in saved and "Generated perception tools" not in saved
    declarations = json.loads((output / "tool-declarations.json").read_text())
    assert {item["name"] for item in declarations} == {"observe", "finish"}
