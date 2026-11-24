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
import math
import os
import threading
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from fastapi import Request
from fastapi.responses import JSONResponse


def install_operator_routes(app, *, session_state=None, operator_lock=None):
    operator_lock = operator_lock or threading.Lock()
    rdk_endpoint = os.environ.get("RPENT_FLEXIV_RDK_ENDPOINT")
    endpoint = (
        rdk_endpoint
        or os.environ.get("RPENT_FLEXIV_COLLECTOR", "http://127.0.0.1:9527")
    ).rstrip("/")

    def path(action):
        if rdk_endpoint:
            return {
                "status": "/state",
                "gripper": "/move_gripper",
                "arm": "/enable",
                "stop": "/stop",
                "home-preview": "/home-preview",
                "reset-home": "/jointreset",
            }[action]
        return "/rpent/operator/" + action

    def operator_status(data):
        if not rdk_endpoint:
            return data
        state = data.get("state", data)
        idle = session_state is not None and session_state() == "ready"
        armed = bool(data.get("armed", data.get("enabled", False)))
        reason = (
            "操作员动作正在执行"
            if operator_lock.locked()
            else "请先结束当前实验"
            if not idle
            else "未配置保存的参考位"
            if not data.get("home_available")
            else "请先启用机械臂"
            if not armed
            else ""
        )
        return {
            **data,
            "control_backend": "rdk",
            "state": state,
            "armed": armed,
            "gripper_ready": bool(data.get("gripper_ready", False)),
            "lease_active": False,
            "gripper_available": bool(
                idle
                and armed
                and data.get("gripper_ready")
                and not operator_lock.locked()
            ),
            "reset_available": not reason,
            "reset_reason": reason,
        }

    def forward(request, action, *, gripper=None):
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
        try:
            timeout = 8
            if rdk_endpoint and action in {"arm", "reset-home", "gripper"}:
                route = "/home-preview" if action == "reset-home" else "/state"
                with urlopen(URLRequest(endpoint + route), timeout=8) as response:
                    preview = json.load(response)
                config = (
                    preview if action == "reset-home" else preview.get("config", {})
                )
                timeout = config.get("timeout_s", 30) + 10
                if action == "gripper":
                    if not preview.get("armed") or not preview.get("gripper_ready"):
                        return JSONResponse(
                            {"error": "请先启用机械臂并连接夹爪"}, status_code=409
                        )
                    width = config.get(
                        "gripper_max_width_m"
                        if gripper == "open"
                        else "gripper_min_width_m"
                    )
                    if type(width) not in (int, float) or not math.isfinite(width):
                        return JSONResponse(
                            {"error": "夹爪行程不可用"}, status_code=409
                        )
                    body = json.dumps({"width_m": width}).encode()
            command = URLRequest(
                endpoint + path(action),
                data=body,
                headers={"Content-Type": "application/json"},
            )
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

    @app.get("/api/flexiv/home-preview")
    def home_preview(request: Request):
        if not rdk_endpoint:
            return JSONResponse(
                {"error": "回参考位仅支持 RDK 控制服务"}, status_code=409
            )
        return forward(request, "home-preview")

    def idle_action(request, action, **kwargs):
        if not rdk_endpoint:
            return JSONResponse({"error": "此操作仅支持 RDK 控制服务"}, status_code=409)
        if not operator_lock.acquire(blocking=False):
            return JSONResponse({"error": "机械臂操作正在执行"}, status_code=409)
        try:
            if session_state is None or session_state() != "ready":
                return JSONResponse({"error": "请先结束当前实验"}, status_code=409)
            return forward(request, action, **kwargs)
        finally:
            operator_lock.release()

    @app.post("/api/flexiv/reset-home")
    def reset_home(request: Request):
        return idle_action(request, "reset-home")

    @app.post("/api/flexiv/gripper/{direction}")
    def gripper(request: Request, direction: Literal["open", "close"]):
        return idle_action(request, "gripper", gripper=direction)

    return interrupt_stop
