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

"""RPent adapter for the standalone Flexiv RDK HTTP service."""

import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from robots.flexiv.rgbd_snapshot import CalibratedRGBD


class RdkBackend(CalibratedRGBD):
    """Forward control to RDK; share only calibrated capture with the old backend."""

    control_backend = "rdk"

    def __init__(self, endpoint, calibration=None, rgbd_dir=None):
        self.endpoint = endpoint.rstrip("/")
        self.calibration = calibration
        self.rgbd_dir = Path(rgbd_dir) if rgbd_dir else None
        self.connection = None

    def request(self, path, data=None):
        command = Request(
            self.endpoint + path,
            data=None if data is None else json.dumps(data, allow_nan=False).encode(),
            headers={"Content-Type": "application/json"},
        )
        timeout = 5 if data is None or path == "/stop" else 40
        if self.connection and path in ("/pose", "/delta", "/move_gripper"):
            timeout = self.connection["config"]["timeout_s"] + 10
        try:
            with urlopen(command, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Flexiv RDK {exc.code}: {exc.read().decode()}") from exc

    def open(self):
        if self.connection is not None:
            raise RuntimeError("An RPent task already owns this environment")
        self.connection = self.request("/state")
        return {"ok": True}

    def get_env_meta(self):
        state = self.connection["state"]
        return {
            "robot": "flexiv",
            "robot_sn": state["robot_sn"],
            "control_backend": "rdk",
            "coordinate_frame": "robot_base",
            "quaternion_order": "wxyz",
            "motion_enabled": bool(self.connection["armed"]),
            "control_limits": self.connection["config"],
            "reset_before_task": False,
            "calibrated_readonly": self.calibration is not None,
            "calibration_provisional": bool(
                getattr(self.calibration, "provisional", False)
            ),
            "operator_confirmed_cameras": getattr(
                self.calibration, "operator_confirmed_cameras", []
            ),
        }

    def calibration_snapshot(self):
        feedback = self.request("/state")
        return {
            "tool": feedback["tool"],
            "state_before": feedback["state"],
            "state_after": feedback["state"],
            "captured_at": time.time(),
        }

    def get_observation(self):
        if self.calibration is None:
            feedback = self.request("/state")
            observed = {
                "state": feedback["state"],
                "images_png": {},
                "missing_cameras": ["side", "wrist"],
            }
        else:
            # Allow the native trajectory to finish settling before a calibrated
            # capture. This never sends a new hold target or stops the robot.
            deadline = time.monotonic() + 3
            while True:
                try:
                    observed = self.calibration.observation(self.rgbd_snapshot())
                    break
                except ValueError as exc:
                    if (
                        str(exc)
                        not in (
                            "Snapshot requires finite stationary robot state",
                            "Robot moved during the calibrated capture",
                        )
                        or time.monotonic() >= deadline
                    ):
                        raise
                    time.sleep(0.05)
            feedback = self.request("/state")
            observed["camera_calibration"]["motion_enabled"] = feedback["armed"]
        observed.update(
            control_backend="rdk",
            control_limits=feedback["config"],
            motion_enabled=feedback["armed"],
            stop_reason=feedback["stop_reason"],
            native_success=None,
        )
        return observed

    def _motion(self, route, payload):
        if self.connection is None or not self.connection["armed"]:
            raise RuntimeError(
                "This task was opened observation-only; enable before starting a new task"
            )
        try:
            return self.request(route, payload)
        except (URLError, TimeoutError, ConnectionError):
            # A transport failure does not prove whether the command executed.
            # Never retry a relative movement; interrupt it through the stop route.
            self.stop_motion()
            raise

    def move_tcp(self, position_m, quaternion_wxyz=None):
        return self._motion(
            "/pose", {"position_m": position_m, "quaternion_wxyz": quaternion_wxyz}
        )

    def move_eef_delta(self, translation_m, rotation_vector_rad):
        return self._motion(
            "/delta",
            {
                "translation_m": translation_m,
                "rotation_vector_rad": rotation_vector_rad,
            },
        )

    def set_gripper(self, width_m):
        return self._motion("/move_gripper", {"width_m": width_m})

    def stop_motion(self):
        return self.request("/stop", {})

    def close(self):
        connection, self.connection = self.connection, None
        if connection and connection["armed"]:
            self.stop_motion()
        return {"ok": True}
