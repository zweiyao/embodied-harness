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

from fastapi import FastAPI
from fastapi.testclient import TestClient

from robots.flexiv import operator_ui


def test_operator_proxy_rejects_foreign_origin_and_forwards_stop(monkeypatch):
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
