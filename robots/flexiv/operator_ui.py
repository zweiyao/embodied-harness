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

"""Operator controls independent of the planner and its serialized RPC calls."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from fastapi import Request
from fastapi.responses import JSONResponse


def install_operator_routes(app):
    rdk_endpoint = os.environ.get("RPENT_FLEXIV_RDK_ENDPOINT")
    endpoint = (
        rdk_endpoint
        or os.environ.get("RPENT_FLEXIV_COLLECTOR", "http://127.0.0.1:9527")
    ).rstrip("/")

    def path(action):
        if rdk_endpoint:
            return {"status": "/state", "arm": "/enable", "stop": "/stop"}[action]
        return "/rpent/operator/" + action

    def operator_status(data):
        if not rdk_endpoint:
            return data
        state = data.get("state", data)
        return {
            **data,
            "control_backend": "rdk",
            "state": state,
            "armed": bool(data.get("armed", data.get("enabled", False))),
            "gripper_ready": bool(data.get("gripper_ready", False)),
            "lease_active": False,
        }

    def forward(request, action):
        origin = request.headers.get("origin")
        if (
            request.method == "POST"
            and origin
            and origin.rstrip("/") != str(request.base_url).rstrip("/")
        ):
            return JSONResponse(
                {"error": "Operator controls require the same origin"}, status_code=403
            )
        body = b"{}" if request.method == "POST" else None
        command = URLRequest(
            endpoint + path(action),
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            timeout = 8
            if rdk_endpoint and action == "arm":
                state_request = URLRequest(endpoint + "/state")
                with urlopen(state_request, timeout=8) as response:
                    config = json.load(response).get("config", {})
                timeout = config.get("timeout_s", 30) + 10
            with urlopen(command, timeout=timeout) as response:
                data = json.load(response)
                return JSONResponse(
                    operator_status(data) if action == "status" else data
                )
        except HTTPError as error:
            detail = error.read().decode()
            return JSONResponse({"error": detail}, status_code=error.code)
        except (URLError, TimeoutError) as error:
            return JSONResponse(
                {
                    "error": f"{'RDK server' if rdk_endpoint else 'Collector'} unavailable: {error}"
                },
                status_code=502,
            )

    def interrupt_stop():
        command = URLRequest(
            endpoint + path("stop"),
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(command, timeout=8) as response:
            return json.load(response)

    @app.get("/api/flexiv/status")
    def status(request: Request):
        return forward(request, "status")

    @app.post("/api/flexiv/arm")
    def arm(request: Request):
        return forward(request, "arm")

    @app.post("/api/flexiv/stop")
    def stop(request: Request):
        return forward(request, "stop")

    return interrupt_stop
