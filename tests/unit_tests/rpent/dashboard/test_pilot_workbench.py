# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Per-run pilot configuration without a planner, simulator or network request."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from robots.univtac.pilot import Pilot
from robots.univtac.robot_spec import DASHBOARD_SPEC
from rpent.dashboard.server import DashboardServer
from rpent.dashboard.state import DashboardState
from rpent.dashboard.workbench import Workbench


@pytest.fixture
def pilot_dashboard(tmp_path, monkeypatch):
    pilot = Pilot.create(tmp_path / "pilot")
    for cell in ("dev-01", "dev-02"):
        attempt = pilot.reserve_episode(cell, cell)
        pilot.finish_episode(attempt, {"termination_reason": "setup_failure"})
    tools = [
        {"id": "native:finish", "name": "finish", "origin": "native"},
        {"id": "native:move_eef", "name": "move_eef", "origin": "native"},
    ]
    monkeypatch.setattr("rpent.dashboard.workbench.native_catalog", lambda robot: tools)
    bench = Workbench(
        {
            "robot": "univtac",
            "runs_root": str(tmp_path / "runs"),
            "library_root": str(tmp_path / "library"),
            "setup": {},
            "models": [
                {"id": "sdk", "planner": "codex", "model": "gpt-6-astra"},
                {"id": "api", "planner": "api", "model": "openai-chat:qwen3.8-max"},
            ],
        },
        robot="univtac",
    )
    bench.bind_pilot(
        pilot.root,
        "dev-03",
        freeze_id=None,
        run_options={"max_turns": 60, "max_tokens": 4096, "planner_timeout_s": 3600},
    )
    bench.checks = {name: {"ok": True} for name in bench.profiles}
    state = DashboardState(
        output_dir=bench.root / "session", dashboard_spec=DASHBOARD_SPEC
    )
    state.workbench = bench
    server = DashboardServer(state=state, robot_name="univtac", planner="codex")
    state.shared_services_ready()
    return pilot, bench, state, TestClient(server._app)


def test_cell_selection_is_frozen_per_run_and_usage_refreshes(pilot_dashboard):
    pilot, bench, state, client = pilot_dashboard
    setup = client.get("/api/setup").json()["pilot"]
    assert setup["selected_cell"] == "dev-03"
    assert (setup["episodes_reserved"], setup["episode_limit"], setup["finished"]) == (
        2,
        40,
        2,
    )
    cells = {cell["id"]: cell for cell in setup["cells"]}
    assert cells["dev-01"]["status"] == "used"
    assert cells["dev-03"]["available"] and cells["dev-03"]["task_index"] == 0
    assert not cells["dev-05"]["available"]
    before = (pilot.root / "events.jsonl").read_text()
    assert (
        client.post(
            "/api/session/messages", json={"text": "/rpent-task univtac 0 2"}
        ).status_code
        == 202
    )
    assert (
        client.post("/api/session/config", json={"pilot_cell": "dev-04"}).status_code
        == 200
    )
    first = state.wait_for_task(0)
    assert first.request["pilot_cell"] == "dev-03"
    assert first.request["seed"] == 2 and first.request["max_turns"] == 60
    assert (pilot.root / "events.jsonl").read_text() == before
    attempt = pilot.reserve_episode("dev-03", "completed-first-run")
    pilot.finish_episode(attempt, {"termination_reason": "failed"})
    state.complete_task(state="failed")
    assert (
        client.post(
            "/api/session/messages", json={"text": "/rpent-task univtac 0 3"}
        ).status_code
        == 202
    )
    second = state.wait_for_task(0)
    assert second.request["pilot_cell"] == "dev-04" and second.request["seed"] == 3
    assert first.request["frozen_tools"] == second.request["frozen_tools"]
    setup = client.get("/api/setup").json()["pilot"]
    assert setup["selected_cell"] == "dev-04" and setup["episodes_reserved"] == 3
    assert bench.pilot.root == pilot.root and bench.pilot_freeze is None


@pytest.mark.parametrize(
    "payload",
    [
        {"pilot_cell": "missing"},
        {"pilot_cell": "dev-01"},
        {"pilot_cell": "dev-05"},
        {"pilot_cell": None},
        {"pilot_cell": []},
        {"pilot_root": "/other"},
        {"pilot_freeze": "other"},
    ],
)
def test_invalid_pilot_config_does_not_mutate_or_charge(pilot_dashboard, payload):
    pilot, _, _, client = pilot_dashboard
    before = client.get("/api/session/config").json()
    events = (pilot.root / "events.jsonl").read_text()
    assert client.post("/api/session/config", json=payload).status_code == 422
    assert client.get("/api/session/config").json() == before
    assert (pilot.root / "events.jsonl").read_text() == events


@pytest.mark.parametrize(
    "config,command",
    [
        ({}, "/rpent-task univtac 1 2"),
        ({}, "/rpent-task univtac 0 3"),
        ({"model_profile": "api"}, "/rpent-task univtac 0 2"),
        ({"max_turns": 25}, "/rpent-task univtac 0 2"),
        ({"planner_timeout_s": 600}, "/rpent-task univtac 0 2"),
    ],
)
def test_start_rejects_mismatched_cell_without_reserving(
    pilot_dashboard, config, command
):
    pilot, _, state, client = pilot_dashboard
    if config:
        assert client.post("/api/session/config", json=config).status_code == 200
    response = client.post("/api/session/messages", json={"text": command})
    assert response.status_code == 422
    assert state.wait_for_task(0) is None
    assert pilot.summary()["episodes_reserved"] == 2


def test_ledger_is_rechecked_before_dispatch(pilot_dashboard):
    pilot, bench, state, _ = pilot_dashboard
    state.request_task({"suite": "univtac", "task": 0, "seed": 2})
    claimed = state.wait_for_task(0)
    pilot.reserve_episode("dev-03", "another-process")
    with pytest.raises(ValueError, match="already been used"):
        bench.validate_pilot_request(claimed.request)


def test_cell_configuration_requires_a_bound_univtac_pilot(pilot_dashboard):
    pilot, bench, state, _ = pilot_dashboard
    bench.pilot = None
    with pytest.raises(ValueError):
        state.set_next_config({"pilot_cell": "dev-03"})
    assert bench.pilot_setup() is None
    bench.robot = "libero"
    with pytest.raises(ValueError, match="only for UniVTAC"):
        bench.bind_pilot(pilot.root, "dev-03")


def test_claimed_cell_overrides_cli_default_in_snapshot(pilot_dashboard, tmp_path):
    from rpent.cli.dashboard import _run_dashboard_task_inner
    from rpent.dashboard.state import ClaimedTask

    pilot, _, state, _ = pilot_dashboard
    args = SimpleNamespace(
        pilot_root=str(pilot.root),
        pilot_cell="dev-03",
        pilot_freeze=None,
        explore=False,
        model="gpt-6-astra",
        max_turns=60,
        max_tokens=4096,
        planner_timeout_s=3600,
    )
    seen = {}

    def parse_config(effective):
        seen.update(vars(effective))
        raise RuntimeError("stop before runtime")

    spec = SimpleNamespace(
        name="univtac", is_real_robot=False, parse_config=parse_config
    )
    claimed = ClaimedTask(
        1, {"pilot_cell": "dev-04", "task": 0, "seed": 3}, tmp_path / "claimed"
    )
    with pytest.raises(RuntimeError, match="stop before runtime"):
        _run_dashboard_task_inner(
            args=args,
            robot_spec=spec,
            state=state,
            claimed=claimed,
            shared_runtime_kwargs={},
            unique_components=set(),
            session_root=tmp_path,
        )
    assert seen["pilot_cell"] == "dev-04" and args.pilot_cell == "dev-03"
    assert seen["pilot_root"] == str(pilot.root) and seen["pilot_freeze"] is None
    snapshot = json.loads((claimed.output_dir / "dashboard_config.json").read_text())
    assert snapshot["task"]["pilot_cell"] == "dev-04"


def test_connectivity_checks_charge_success_failure_and_exception(
    pilot_dashboard, monkeypatch
):
    pilot, bench, _, _ = pilot_dashboard
    responses = [True, False]

    def check(request):
        assert pilot.summary()["offline_requests"] == 3 - len(responses)
        if responses:
            ok = responses.pop(0)
            return SimpleNamespace(
                as_dict=lambda: {"ok": ok, "status": "ok" if ok else "network_failure"}
            )
        raise ConnectionError("offline fixture")

    monkeypatch.setattr("rpent.planner.check.check_llm", check)
    assert bench.check("sdk")["ok"]
    assert not bench.check("sdk")["ok"]
    with pytest.raises(ConnectionError, match="offline fixture"):
        bench.check("sdk")
    assert pilot.summary()["offline_requests"] == 3
    assert not bench.checks["sdk"]["ok"]
    events = [
        json.loads(line)
        for line in (pilot.root / "events.jsonl").read_text().splitlines()
    ]
    records = [event for event in events if event["kind"] == "offline_result"]
    assert len(records) == 3 and records[-1]["result"]["status"] == "error"


def test_exhausted_connectivity_budget_does_not_dispatch(pilot_dashboard, monkeypatch):
    pilot, bench, _, _ = pilot_dashboard
    for _ in range(80):
        pilot.reserve_offline("connectivity", None, [])
    monkeypatch.setattr(
        "rpent.planner.check.check_llm", lambda _: pytest.fail("request was sent")
    )
    with pytest.raises(ValueError, match="offline request budget exhausted"):
        bench.check("sdk")


def test_history_includes_only_internal_episode_video_link(pilot_dashboard, tmp_path):
    _, bench, _, _ = pilot_dashboard
    root = bench.root / "session/tasks/1"
    video = root / "native/video/1.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video fixture")
    (root / "dashboard_config.json").write_text("{}")
    (root / "episode.mp4").symlink_to("native/video/1.mp4")
    (root / "other.mp4").symlink_to("native/video/1.mp4")
    run = bench.runs()[0]
    files = bench.run(run["id"])["files"]
    assert "episode.mp4" in files and "other.mp4" not in files
    assert bench.artifact(run["id"], "episode.mp4") == video
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    (root / "episode.mp4").unlink()
    (root / "episode.mp4").symlink_to(outside)
    assert "episode.mp4" not in bench.run(run["id"])["files"]
    with pytest.raises(ValueError, match="Unknown artifact"):
        bench.artifact(run["id"], "episode.mp4")
