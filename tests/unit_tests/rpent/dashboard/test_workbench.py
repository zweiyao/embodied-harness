# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Manual workbench selection, persistence and credential boundaries."""

import json
import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from rpent.dashboard.server import DashboardServer
from rpent.dashboard.state import DashboardState
from rpent.dashboard.workbench import (
    RunJournal,
    Workbench,
    publish,
    source_snapshot,
    termination_reason,
)
from tests.unit_tests.rpent.dashboard.test_server_contracts import DASHBOARD_SPEC


def test_source_snapshot_skips_appledouble_metadata(tmp_path):
    root = tmp_path / "repo"
    source = root / "rpent" / "dashboard"
    source.mkdir(parents=True)
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (source / "example.py").write_text("answer = 42\n")
    (source / "._example.py").write_bytes(b"\x00\x05\x16\x07\xa3")
    output = tmp_path / "snapshot"
    output.mkdir()

    snapshot = source_snapshot(root, output)

    assert set(snapshot["files"]) == {"rpent/dashboard/example.py"}
    assert (output / "code/rpent/dashboard/example.py").read_text() == "answer = 42\n"
    assert not (output / "code/rpent/dashboard/._example.py").exists()


@pytest.fixture
def bench(tmp_path):
    return Workbench(
        {
            "runs_root": str(tmp_path),
            "library_root": str(tmp_path / "library"),
            "setup": {},
            "models": [
                {"id": "api", "planner": "api", "model": "openai-chat:test"},
                {"id": "sdk", "planner": "codex", "model": "test"},
            ],
        }
    )


def candidate():
    return {
        "name": "sensor_test",
        "description": "fixture",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "source": 'def run(frames, params): return {"count": len(frames)}\n',
    }


def test_selection_is_explicit_and_versions_frozen(bench):
    version = publish(bench.library, candidate(), {"dependencies": ["back_project"]})
    assert all(t["origin"] == "native" for t in bench.selection())
    finish = ["native:finish"]
    for invalid in (
        [],
        finish * 2,
        finish + ["generated:missing"],
        finish + ["generated:" + version],
    ):
        with pytest.raises(ValueError):
            bench.selection(invalid)
    ids = finish + ["native:back_project", "generated:" + version]
    with pytest.raises(ValueError):
        bench.prepare({"tools": ids})
    bench.checks = {p: {"ok": True} for p in bench.profiles}
    frozen = bench.prepare({"tools": ids})
    new = candidate()
    new["source"] = 'def run(frames, params): return {"changed": True}\n'
    v2 = publish(bench.library, new, {"previous_version": version})
    assert frozen["frozen_tools"][-1]["source"] == candidate()["source"]
    with pytest.raises(ValueError):
        bench.selection(ids + ["generated:" + v2])
    assert [t["version"] for t in bench.catalog() if t["origin"] == "generated"] == [v2]
    assert not (bench.library / f"{version}.json").exists()
    assert not (bench.library / f"{version}.meta.json").exists()
    # Retrying a publication must not require the removed predecessor.
    assert publish(bench.library, new, {"previous_version": version}) == v2
    other = {**candidate(), "name": "sensor_other"}
    other_version = publish(bench.library, other, {})
    assert {t["version"] for t in bench.catalog() if t["origin"] == "generated"} == {
        v2,
        other_version,
    }


def test_server_rejects_unknown_and_arbitrary_model(bench, tmp_path):
    state = DashboardState(
        output_dir=tmp_path / "session", dashboard_spec=DASHBOARD_SPEC
    )
    state.workbench = bench
    state.shared_services_ready()
    client = TestClient(
        DashboardServer(state=state, robot_name="libero", planner="api")._app
    )
    assert (
        client.post("/api/session/config", json={"model": "bypass"}).status_code == 422
    )
    assert (
        client.post(
            "/api/session/config", json={"tools": ["native:finish"]}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/session/config", json={"tools": ["native:missing"]}
        ).status_code
        == 422
    )
    bench.checks = {p: {"ok": True} for p in bench.profiles}
    state.request_task({"seed": 1})
    state.set_next_config({"tools": ["native:finish", "native:segment"]})
    first = state.wait_for_task(0)
    assert first.request["tools"] == ["native:finish"]
    state.complete_task(state="succeeded")
    second_state = DashboardState(
        output_dir=tmp_path / "session", dashboard_spec=DASHBOARD_SPEC
    )
    second_state.workbench = bench
    second_state.shared_services_ready()
    second_state.request_task({"seed": 1})
    assert second_state.wait_for_task(0).output_dir != first.output_dir


def test_journal_persists_errors_and_redacts_secrets(bench, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value-12345")
    root = tmp_path / "session/tasks/0001_s1"
    root.mkdir(parents=True)
    (root / "dashboard_config.json").write_text("{}")
    log = RunJournal(root)
    log.append(
        "model_request",
        {"authorization": "x", "nested": "secret-value-12345", "image": b"abc"},
    )
    log.append("tool_error", {"error": "connection failed"})
    lines = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()]
    assert lines[0]["payload"]["authorization"] == "[redacted]"
    assert lines[0]["payload"]["nested"] == "[redacted]"
    assert (root / lines[0]["payload"]["image"]["artifact"]).read_bytes() == b"abc"
    run = bench.runs()[0]
    assert bench.run(run["id"])["files"]
    with pytest.raises(ValueError):
        bench.artifact(run["id"], "../../../../outside")
    assert (
        termination_reason("ConnectionError", False, None, False) == "network_failure"
    )
    assert termination_reason(None, True, None, False) == "aborted"
    assert termination_reason("timed out", False, None, False) == "timeout"


def test_profile_credentials_are_restored(bench, tmp_path, monkeypatch):
    secret = tmp_path / "key"
    secret.write_text("test-secret")
    bench.profiles["api"]["key_file"] = str(secret)
    monkeypatch.setenv("CODEX_HOME", "before")
    with bench.environment("api"):
        import os

        assert os.environ["OPENAI_API_KEY"] == "test-secret"
        assert "CODEX_HOME" not in os.environ
    assert os.environ["CODEX_HOME"] == "before"


def test_only_selected_model_must_pass_connection_check(bench):
    bench.checks = {"api": {"ok": True}, "sdk": {"ok": False}}
    assert bench.prepare({"model_profile": "api"})["model_profile"] == "api"
    with pytest.raises(ValueError, match="所选模型"):
        bench.prepare({"model_profile": "sdk"})


@pytest.mark.parametrize("profile_id", ["api", "sdk"])
def test_model_profiles_preserve_server_network_environment(
    bench, monkeypatch, profile_id
):
    network = {
        "HTTP_PROXY": "http://remote-proxy.invalid:8080",
        "HTTPS_PROXY": "http://remote-proxy.invalid:8080",
        "ALL_PROXY": "socks5://remote-proxy.invalid:1080",
        "http_proxy": "http://remote-proxy.invalid:8080",
        "https_proxy": "http://remote-proxy.invalid:8080",
        "all_proxy": "socks5://remote-proxy.invalid:1080",
        "NO_PROXY": "localhost,127.0.0.1,::1",
        "no_proxy": "localhost,127.0.0.1,::1",
    }
    for key, value in network.items():
        monkeypatch.setenv(key, value)
    with bench.environment(profile_id):
        assert {key: os.environ.get(key) for key in network} == network
    with pytest.raises(RuntimeError, match="probe failed"):
        with bench.environment(profile_id):
            assert {key: os.environ.get(key) for key in network} == network
            raise RuntimeError("probe failed")
    assert {key: os.environ.get(key) for key in network} == network


def test_network_startup_failure_is_durable_and_not_task_failure(
    bench, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from rpent.cli import dashboard

    root = tmp_path / "session/tasks/0001_s1"
    root.mkdir(parents=True)
    state = SimpleNamespace(
        workbench=bench,
        workbench_aborted=False,
        run_id="fixture",
        journal=RunJournal(root),
    )
    claimed = SimpleNamespace(
        output_dir=root,
        request={
            "model_profile": "api",
            "frozen_tools": bench.selection(["native:finish"]),
        },
    )
    monkeypatch.setattr("rpent.utils.config.get_repo_root", lambda: tmp_path)
    monkeypatch.setattr("rpent.dashboard.workbench.source_snapshot", lambda *args: {})

    def fail(**kwargs):
        state.journal.append("model_request", {"prompt": "fixture"})
        raise ConnectionError("simulated disconnect")

    monkeypatch.setattr(dashboard, "_run_dashboard_task_inner", fail)
    with pytest.raises(ConnectionError):
        dashboard._run_dashboard_task(
            args=SimpleNamespace(),
            robot_spec=SimpleNamespace(name="libero"),
            state=state,
            claimed=claimed,
        )
    outcome = json.loads((root / "outcome.json").read_text())
    assert outcome["status"] == "network_failure"
    assert outcome["environment_success"] is None
    assert bench.runs()[0]["outcome"] == outcome
    assert len((root / "events.jsonl").read_text().splitlines()) == 2


def test_restart_recovers_only_unfinished_runs(bench, tmp_path):
    root = tmp_path / "session/tasks/0001_s1"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    (root / "events.jsonl").write_text('{"kind":"tool_request"}\n')
    bench.recover_interrupted()
    assert json.loads((root / "outcome.json").read_text())["status"] == "abnormal_exit"
    assert (root / "events.jsonl").read_text() == '{"kind":"tool_request"}\n'
    (root / "outcome.json").write_text(
        '{"status":"completed","environment_success":true}'
    )
    bench.recover_interrupted()
    assert (
        json.loads((root / "outcome.json").read_text())["environment_success"] is True
    )


def test_abort_uses_native_drain_without_scheduling_another_task(bench, tmp_path):
    state = DashboardState(
        output_dir=tmp_path / "session", dashboard_spec=DASHBOARD_SPEC
    )
    state.workbench = bench
    state.shared_services_ready()
    bench.checks = {p: {"ok": True} for p in bench.profiles}
    state.request_task({"seed": 1})
    first = state.wait_for_task(0)
    client = TestClient(
        DashboardServer(state=state, robot_name="libero", planner="api")._app
    )
    assert client.post("/api/session/abort").status_code == 200
    assert state.workbench_aborted and state.task_replacement_requested
    state.complete_task_replacement()
    state.complete_task(state="cancelled")
    assert state.session_state == "ready"
    assert state.wait_for_task(0) is None
    assert "operator_abort" in (first.output_dir / "events.jsonl").read_text()


def test_manual_experiments_preserve_scene_config_without_pilot_cells(bench, tmp_path):
    bench.checks = {"api": {"ok": True}}
    state = DashboardState(
        output_dir=tmp_path / "session", dashboard_spec=DASHBOARD_SPEC
    )
    state.workbench = bench
    state.shared_services_ready()
    state.set_next_config({"model_profile": "api", "tools": ["native:finish"]})
    request = {"suite": "univtac", "task": 0, "seed": 2}
    assert bench.pilot_setup() is None
    state.request_task(request)
    first = state.wait_for_task(0)
    state.complete_task(state="succeeded")
    state.request_task(request)
    second = state.wait_for_task(0)
    assert first.output_dir != second.output_dir
    for run in (first, second):
        assert all(run.request[key] == value for key, value in request.items())
        assert run.request["model_profile"] == "api"
        assert run.request["tools"] == ["native:finish"]
        assert "pilot_cell" not in run.request
