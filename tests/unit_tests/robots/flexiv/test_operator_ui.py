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
