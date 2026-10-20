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
    endpoint = os.environ.get("RPENT_FLEXIV_COLLECTOR", "http://127.0.0.1:9527").rstrip(
        "/"
    )

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
            endpoint + "/rpent/operator/" + action,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(command, timeout=8) as response:
                return JSONResponse(json.load(response))
        except HTTPError as error:
            detail = error.read().decode()
            return JSONResponse({"error": detail}, status_code=error.code)
        except (URLError, TimeoutError) as error:
            return JSONResponse(
                {"error": f"Collector unavailable: {error}"}, status_code=502
            )

    def interrupt_stop():
        command = URLRequest(
            endpoint + "/rpent/operator/stop",
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
