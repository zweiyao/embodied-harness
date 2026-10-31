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

"""Operator endpoints are independent of planner calls and reject foreign origins."""

import io
import json
import threading
from urllib.error import HTTPError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from robots.flexiv import operator_ui


def test_operator_proxy_rejects_foreign_origin_and_forwards_stop(monkeypatch):
    monkeypatch.delenv("RPENT_FLEXIV_RDK_ENDPOINT", raising=False)
    calls = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(b'{"stopped":true}')

    monkeypatch.setattr(operator_ui, "urlopen", urlopen)
    app = FastAPI()
    interrupt = operator_ui.install_operator_routes(app)
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/flexiv/arm", headers={"origin": "https://outside.invalid"}
            ).status_code
            == 403
        )
        assert calls == []
        assert client.post(
            "/api/flexiv/stop", headers={"origin": "http://testserver"}
        ).json()["stopped"]
    assert interrupt()["stopped"]
    assert all(p.endswith("/rpent/operator/stop") for p in calls)


def test_operator_rdk_routes_use_direct_server_and_keep_ui_contract(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_method(), request.full_url))
        return io.BytesIO(
            b'{"armed":true,"gripper_ready":true,"tcp_pose":[0.4,0,0.2,1,0,0,0],"mode":"NRT_CARTESIAN_MOTION_FORCE"}'
        )

    monkeypatch.setenv("RPENT_FLEXIV_RDK_ENDPOINT", "http://rdk:5000/")
    monkeypatch.setenv("RPENT_FLEXIV_COLLECTOR", "http://unused-collector:9527")
    monkeypatch.setattr(operator_ui, "urlopen", urlopen)
    app = FastAPI()
    interrupt = operator_ui.install_operator_routes(app)
    with TestClient(app) as client:
        state = client.get("/api/flexiv/status").json()
        assert state["armed"] and state["gripper_ready"]
        assert state["control_backend"] == "rdk" and not state["lease_active"]
        assert state["state"]["tcp_pose"][2] == 0.2
        assert client.post("/api/flexiv/arm").status_code == 200
        assert client.post("/api/flexiv/stop").status_code == 200
        assert (
            client.post(
                "/api/flexiv/arm", headers={"origin": "https://outside.invalid"}
            ).status_code
            == 403
        )
    interrupt()
    assert calls == [
        ("GET", "http://rdk:5000/state"),
        ("GET", "http://rdk:5000/state"),
        ("POST", "http://rdk:5000/enable"),
        ("POST", "http://rdk:5000/stop"),
        ("POST", "http://rdk:5000/stop"),
    ]


@pytest.mark.parametrize(
    "config,expected_timeout", [({}, 40), ({"timeout_s": 120}, 130)]
)
def test_rdk_enable_proxy_waits_for_native_enable_deadline(
    monkeypatch, config, expected_timeout
):
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_method(), request.full_url, timeout))
        if request.full_url.endswith("/state"):
            return io.BytesIO(json.dumps({"config": config}).encode())
        # A slow native enable is still within its configured deadline. The
        # former eight-second proxy timeout would fail before this response.
        if timeout < expected_timeout:
            raise TimeoutError("Native enable is still running")
        return io.BytesIO(b'{"armed":true}')

    monkeypatch.setenv("RPENT_FLEXIV_RDK_ENDPOINT", "http://rdk:5000")
    monkeypatch.setattr(operator_ui, "urlopen", urlopen)
    app = FastAPI()
    operator_ui.install_operator_routes(app)
    with TestClient(app) as client:
        response = client.post("/api/flexiv/arm")
        assert response.status_code == 200
        assert response.json()["armed"]
    assert calls == [
        ("GET", "http://rdk:5000/state", 8),
        ("POST", "http://rdk:5000/enable", expected_timeout),
    ]


@pytest.mark.parametrize(
    "armed,available,session,enabled,reason",
    [
        (True, True, "ready", True, ""),
        (False, True, "ready", False, "请先启用机械臂"),
        (True, False, "ready", False, "未配置保存的参考位"),
        (True, True, "running", False, "请先结束当前实验"),
    ],
)
def test_rdk_reset_availability(
    monkeypatch, armed, available, session, enabled, reason
):
    monkeypatch.setenv("RPENT_FLEXIV_RDK_ENDPOINT", "http://rdk:5000")
    monkeypatch.setattr(
        operator_ui,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(
            json.dumps({"armed": armed, "home_available": available}).encode()
        ),
    )
    app = FastAPI()
    operator_ui.install_operator_routes(app, session_state=lambda: session)
    with TestClient(app) as client:
        data = client.get("/api/flexiv/status").json()
    assert data["reset_available"] is enabled
    assert data["reset_reason"] == reason


def test_rdk_reset_preview_is_read_only_and_reset_uses_native_timeout(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_method(), request.full_url, timeout, request.data))
        if request.full_url.endswith("/home-preview"):
            return io.BytesIO(b'{"available":true,"timeout_s":120}')
        return io.BytesIO(b'{"reached":true,"motion":"MoveJ"}')

    monkeypatch.setenv("RPENT_FLEXIV_RDK_ENDPOINT", "http://rdk:5000")
    monkeypatch.setattr(operator_ui, "urlopen", urlopen)
    app = FastAPI()
    operator_ui.install_operator_routes(app, session_state=lambda: "ready")
    with TestClient(app) as client:
        assert client.get("/api/flexiv/home-preview").json()["available"]
        assert calls == [("GET", "http://rdk:5000/home-preview", 8, None)]
        assert client.post("/api/flexiv/reset-home").json()["reached"]
    assert calls[-2:] == [
        ("GET", "http://rdk:5000/home-preview", 8, None),
        ("POST", "http://rdk:5000/jointreset", 130, b"{}"),
    ]


@pytest.mark.parametrize(
    "session", ["running", "task_starting", "switch_pending", None]
)
def test_rdk_reset_rejects_active_or_unknown_session(monkeypatch, session):
    monkeypatch.setenv("RPENT_FLEXIV_RDK_ENDPOINT", "http://rdk:5000")
    calls = []
    monkeypatch.setattr(operator_ui, "urlopen", lambda *a, **kw: calls.append(a))
    app = FastAPI()
    operator_ui.install_operator_routes(app, session_state=lambda: session)
    with TestClient(app) as client:
        assert client.post("/api/flexiv/reset-home").status_code == 409
    assert not calls


def test_rdk_reset_rejects_foreign_origin_and_preserves_native_failure(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith("/home-preview"):
            return io.BytesIO(b'{"available":true,"timeout_s":30}')
        raise HTTPError(
            request.full_url, 409, "Conflict", {}, io.BytesIO(b'"Robot is not armed"')
        )

    monkeypatch.setenv("RPENT_FLEXIV_RDK_ENDPOINT", "http://rdk:5000")
    monkeypatch.setattr(operator_ui, "urlopen", urlopen)
    app = FastAPI()
    operator_ui.install_operator_routes(app, session_state=lambda: "ready")
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/flexiv/reset-home", headers={"origin": "https://outside.invalid"}
            ).status_code
            == 403
        )
        assert not calls
        response = client.post("/api/flexiv/reset-home")
    assert response.status_code == 409
    assert "not armed" in response.json()["error"]
    assert len(calls) == 2  # No retry or implicit enable.


def test_reset_lock_does_not_block_stop(monkeypatch):
    monkeypatch.setenv("RPENT_FLEXIV_RDK_ENDPOINT", "http://rdk:5000")
    calls = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(b'{"stopped":true}')

    monkeypatch.setattr(operator_ui, "urlopen", urlopen)
    lock = threading.Lock()
    app = FastAPI()
    operator_ui.install_operator_routes(
        app, session_state=lambda: "ready", operator_lock=lock
    )
    with lock, TestClient(app) as client:
        assert client.post("/api/flexiv/reset-home").status_code == 409
        assert client.post("/api/flexiv/stop").json()["stopped"]
    assert calls == ["http://rdk:5000/stop"]


def test_collector_reset_is_explicitly_unavailable(monkeypatch):
    monkeypatch.delenv("RPENT_FLEXIV_RDK_ENDPOINT", raising=False)
    app = FastAPI()
    operator_ui.install_operator_routes(app, session_state=lambda: "ready")
    with TestClient(app) as client:
        assert client.get("/api/flexiv/home-preview").status_code == 409
        assert client.post("/api/flexiv/reset-home").status_code == 409
