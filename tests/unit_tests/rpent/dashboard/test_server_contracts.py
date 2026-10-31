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

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from rpent.dashboard.server import DashboardServer
from rpent.dashboard.spec import DashboardSpec
from rpent.dashboard.state import DashboardState
from rpent.planner import check as check_mod
from rpent.planner.check import (
    STATUS_AUTH_FAILED,
    STATUS_OK,
    LlmCheckRequest,
    LlmCheckResult,
)

DASHBOARD_SPEC: DashboardSpec = {
    "task": {
        "command": "/rpent-task",
        "usage": "/rpent-task <seed>",
        "fields": ({"name": "seed", "kind": "integer", "minimum": 0},),
        "display": "seed {seed}",
        "output_slug": "s{seed}",
    },
    "runtime_components": (),
    "primitives": (),
}


@pytest.fixture
def state(tmp_path: Path) -> DashboardState:
    return DashboardState(output_dir=tmp_path, dashboard_spec=DASHBOARD_SPEC)


def _server(state: DashboardState, **kwargs: Any) -> DashboardServer:
    return DashboardServer(state=state, **kwargs)


def _client(server: DashboardServer) -> TestClient:
    return TestClient(server._app)


def test_flexiv_catalog_idle_active_and_finished_are_readonly(state, monkeypatch):
    from unittest.mock import MagicMock

    from robots.flexiv.toolkit import FlexivToolkit
    from rpent.tools.toolkit import Toolkit

    monkeypatch.delenv("RPENT_FLEXIV_TOOL_LIBRARY", raising=False)
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    server = _server(state, robot_name="flexiv", run_options={"control_mode": "rdk"})
    client = _client(server)
    assert client.get("/api/setup").json()["tool_catalog"] is True
    idle = client.get("/api/tools").json()
    assert idle["selectable"] is False
    assert len(idle["tools"]) == 12
    assert all(item["availability"] == "conditional" for item in idle["tools"])
    move = client.get("/api/tools/native:move_eef_delta").json()
    assert move["parameters"] == FlexivToolkit.rdk_move_eef_delta.input_schema
    assert client.get("/api/tools/native:reset_home").status_code == 404
    toolkit = MagicMock(spec=Toolkit)
    toolkit.list_tools.return_value = (FlexivToolkit.observe,)
    state.bind_toolkit(toolkit)
    try:
        active = client.get("/api/tools").json()["tools"]
        assert [
            item["name"] for item in active if item["availability"] == "registered"
        ] == ["observe"]
        assert all(
            item["availability"] == "not_registered"
            for item in active
            if item["name"] != "observe"
        )
        toolkit.execute_tool.assert_not_called()
    finally:
        state.unbind_toolkit(toolkit)
    assert all(
        item["availability"] == "conditional"
        for item in client.get("/api/tools").json()["tools"]
    )
    assert state.snapshot()["pending_task"] is None


def test_workbench_catalog_keeps_its_existing_items(state):
    from types import SimpleNamespace

    server = _server(state, robot_name="libero")
    items = [{"id": "native:example", "name": "example", "parameters": {}}]
    server._workbench = SimpleNamespace(catalog=lambda: items)
    client = _client(server)
    assert client.get("/api/tools").json()["tools"] == items
    assert client.get("/api/tools").json()["selectable"] is True
    assert client.get("/api/tools/native:example").json() == items[0]


def test_flexiv_selection_is_frozen_before_task_claim(tmp_path, monkeypatch):
    from robots.flexiv.robot_spec import DASHBOARD_SPEC as FLEXIV_SPEC
    from rpent.dashboard.workbench import Workbench

    monkeypatch.delenv("RPENT_TOOL_CATALOG", raising=False)
    state = DashboardState(output_dir=tmp_path / "session", dashboard_spec=FLEXIV_SPEC)
    state.workbench = Workbench(
        {
            "robot": "flexiv",
            "control_mode": "rdk",
            "runs_root": str(tmp_path),
            "library_root": str(tmp_path / "library"),
            "setup": {},
            "models": [{"id": "astra", "planner": "codex", "model": "gpt-6-astra"}],
        },
        robot="flexiv",
    )
    state.workbench.checks["astra"] = {"ok": True}
    state.shared_services_ready()
    client = _client(_server(state, robot_name="flexiv", planner="codex"))
    assert client.get("/api/tools").json()["selectable"] is True
    chosen = ["native:finish", "native:observe"]
    assert client.post("/api/session/config", json={"tools": chosen}).status_code == 200
    state.request_task({"instruction": "Observe only."})
    assert (
        client.post(
            "/api/session/config", json={"tools": chosen + ["native:move_tcp"]}
        ).status_code
        == 200
    )
    run = state.wait_for_task(0)
    assert run.request["tools"] == chosen
    assert [item["name"] for item in run.request["frozen_tools"]] == [
        "finish",
        "observe",
    ]
    assert (
        client.post(
            "/api/session/config", json={"tools": ["native:finish", "native:move_to"]}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/session/config", json={"control_mode": "native"}).status_code
        == 422
    )


def test_flexiv_reset_blocks_new_tasks_and_primitives_but_not_stop(state, monkeypatch):
    import io
    from concurrent.futures import ThreadPoolExecutor

    from robots.flexiv import operator_ui

    entered = threading.Event()
    release = threading.Event()

    def urlopen(request, timeout):
        if request.full_url.endswith("/home-preview"):
            return io.BytesIO(b'{"available":true,"timeout_s":30}')
        if request.full_url.endswith("/jointreset"):
            entered.set()
            assert release.wait(timeout=5)
            return io.BytesIO(b'{"reached":true}')
        assert request.full_url.endswith("/stop")
        return io.BytesIO(b'{"stopped":true}')

    monkeypatch.setenv("RPENT_FLEXIV_RDK_ENDPOINT", "http://fake-rdk:5000")
    monkeypatch.setattr(operator_ui, "urlopen", urlopen)
    state.shared_services_ready()
    with _client(_server(state, robot_name="flexiv")) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            reset = pool.submit(client.post, "/api/flexiv/reset-home")
            try:
                assert entered.wait(timeout=5)
                assert (
                    client.post(
                        "/api/session/messages", json={"text": "/rpent-task 1"}
                    ).status_code
                    == 409
                )
                assert (
                    client.post(
                        "/api/session/primitive", json={"name": "move", "arguments": {}}
                    ).status_code
                    == 409
                )
                assert client.post("/api/flexiv/stop").json()["stopped"]
                assert state.session_state == "ready"
            finally:
                release.set()
            assert reset.result().json()["reached"]
        assert (
            client.post(
                "/api/session/messages", json={"text": "/rpent-task 1"}
            ).status_code
            == 202
        )
        assert client.post("/api/flexiv/reset-home").status_code == 409


def test_model_change_applies_at_next_task_boundary(state):
    client = _client(_server(state, planner="codex", model="gpt-5.5"))
    state.shared_services_ready()
    state.request_task({"seed": 1})
    first = state.wait_for_task(timeout=0)
    response = client.post("/api/session/config", json={"model": "gpt-6-astra"})
    assert response.status_code == 200
    assert "model" not in first.request
    state.request_task({"seed": 2})
    second = state.wait_for_task(timeout=0)
    assert second.request["model"] == "gpt-6-astra"
    assert client.post("/api/session/config", json={"model": ""}).status_code == 422
    assert (
        client.post("/api/session/config", json={"planner": "api"}).status_code == 422
    )
    assert (
        _client(_server(state, planner="flash"))
        .post("/api/session/config", json={"model": "gpt-6-astra"})
        .status_code
        == 422
    )


def _stub_check(
    monkeypatch: pytest.MonkeyPatch, result: LlmCheckResult
) -> dict[str, Any]:
    """Patch the shared check at its source and capture the request."""
    captured: dict[str, Any] = {}

    def fake_check(request: LlmCheckRequest) -> LlmCheckResult:
        captured["request"] = request
        return result

    monkeypatch.setattr(check_mod, "check_llm", fake_check)
    return captured


def test_check_route_returns_200_and_the_full_result_on_success(
    monkeypatch: pytest.MonkeyPatch, state: DashboardState
) -> None:
    result = LlmCheckResult(
        ok=True,
        status=STATUS_OK,
        planner="api",
        model="anthropic:m",
        reply="ok",
        latency_s=0.4,
    )
    _stub_check(monkeypatch, result)

    resp = _client(_server(state)).post(
        "/api/llm/check", json={"planner": "api", "model": "anthropic:m"}
    )

    assert resp.status_code == 200
    assert resp.json() == result.as_dict()


def test_a_failed_check_is_still_a_successful_request(
    monkeypatch: pytest.MonkeyPatch, state: DashboardState
) -> None:
    _stub_check(
        monkeypatch,
        LlmCheckResult(
            ok=False,
            status=STATUS_AUTH_FAILED,
            planner="api",
            detail="ModelHTTPError: status_code: 401",
        ),
    )

    resp = _client(_server(state)).post("/api/llm/check", json={"model": "anthropic:m"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == STATUS_AUTH_FAILED
    assert "401" in body["detail"]


def test_server_side_base_url_is_merged_into_the_request(
    monkeypatch: pytest.MonkeyPatch, state: DashboardState
) -> None:
    captured = _stub_check(
        monkeypatch,
        LlmCheckResult(ok=True, status=STATUS_OK, planner="api"),
    )
    server = _server(state, planner="codex", base_url="https://gw.example")

    _client(server).post("/api/llm/check", json={"planner": "api", "model": "a:b"})

    request = captured["request"]
    # The request wins on planner/model; the server supplies what it cannot know.
    assert request.planner == "api"
    assert request.model == "a:b"
    assert request.base_url == "https://gw.example"


def test_the_server_planner_default_applies_when_the_form_omits_it(
    monkeypatch: pytest.MonkeyPatch, state: DashboardState
) -> None:
    captured = _stub_check(
        monkeypatch,
        LlmCheckResult(ok=True, status=STATUS_OK, planner="codex"),
    )
    server = _server(state, planner="codex")

    _client(server).post("/api/llm/check", json={})

    assert captured["request"].planner == "codex"


def test_the_run_timeout_is_never_inherited_by_the_check(
    monkeypatch: pytest.MonkeyPatch, state: DashboardState
) -> None:
    captured = _stub_check(
        monkeypatch,
        LlmCheckResult(ok=True, status=STATUS_OK, planner="api"),
    )
    server = _server(state, planner="api")

    _client(server).post("/api/llm/check", json={"model": "a:b"})

    # timeout_s stays None so the check applies its own 30s/90s defaults.
    assert captured["request"].timeout_s is None
    assert captured["request"].resolved_timeout_s() == 30


def test_a_concurrent_check_is_rejected_with_409(
    monkeypatch: pytest.MonkeyPatch, state: DashboardState
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocking_check(request: LlmCheckRequest) -> LlmCheckResult:
        entered.set()
        release.wait(timeout=5)
        return LlmCheckResult(ok=True, status=STATUS_OK, planner="api")

    monkeypatch.setattr(check_mod, "check_llm", blocking_check)
    client = _client(_server(state))
    responses: list[int] = []

    def first_call() -> None:
        responses.append(
            client.post("/api/llm/check", json={"model": "a:b"}).status_code
        )

    worker = threading.Thread(target=first_call, daemon=True)
    worker.start()
    assert entered.wait(timeout=5), "the first check never started"

    second = client.post("/api/llm/check", json={"model": "a:b"})
    assert second.status_code == 409
    assert "already running" in second.json()["error"]

    release.set()
    worker.join(timeout=5)
    assert responses == [200]


def test_the_lock_is_released_after_a_failing_check(
    monkeypatch: pytest.MonkeyPatch, state: DashboardState
) -> None:
    def exploding_check(request: LlmCheckRequest) -> LlmCheckResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(check_mod, "check_llm", exploding_check)
    server = _server(state)
    client = _client(server)

    with pytest.raises(RuntimeError):
        client.post("/api/llm/check", json={"model": "a:b"})

    # A crashed check must not wedge the endpoint for the rest of the session.
    assert server._llm_check_lock.acquire(blocking=False)
    server._llm_check_lock.release()


def test_healthz_still_reports_transport_liveness_only(state: DashboardState) -> None:
    resp = _client(_server(state)).get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.parametrize(
    "payload",
    [
        {"max_turns": 0},
        {"max_turns": True},
        {"max_turns": 301},
        {"max_tokens": "8192"},
        {"planner_timeout_s": 9},
        {"max_tokens": 32769},
        {"planner_timeout_s": 7201},
        {"allow_motion": True},
        {"base_url": "http://example.com"},
        {},
    ],
)
def test_invalid_next_config_is_atomic(state, payload):
    client = _client(_server(state, model="original"))
    original = client.get("/api/session/config").json()
    assert client.post("/api/session/config", json=payload).status_code == 422
    assert client.get("/api/session/config").json() == original


def test_budget_change_is_isolated_from_claimed_task(state):
    client = _client(_server(state, planner="api"))
    state.shared_services_ready()
    state.request_task({"seed": 0})
    first = state.wait_for_task(timeout=0)
    config = {
        "model": " qwen ",
        "max_turns": 30,
        "max_tokens": 2048,
        "planner_timeout_s": 180,
    }
    assert client.post("/api/session/config", json=config).status_code == 200
    config["model"] = "qwen"
    state.request_task({"seed": 1})
    second = state.wait_for_task(timeout=0)
    assert second.request == {"seed": 1, **config}
    assert first.request == {"seed": 0}
    client.post("/api/session/config", json={"max_turns": 80})
    assert second.request["max_turns"] == 30


def test_opt_in_start_screen_keeps_console(state, tmp_path, monkeypatch):
    import json

    setup_file = tmp_path / "setup.json"
    setup_file.write_text(json.dumps({"profiles": [{"robot": "flexiv"}]}))
    monkeypatch.setenv("RPENT_DASHBOARD_SETUP", str(setup_file))
    client = _client(_server(state, robot_name="flexiv"))
    assert 'id="setupForm"' in client.get("/").text
    assert 'id="chatInput"' in client.get("/console").text
    assert client.get("/api/setup").json()["robot"] == "flexiv"
    assert client.get("/static/setup.js").status_code == 200
    assert client.get("/static/setup.css").status_code == 200
