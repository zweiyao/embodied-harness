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

"""RPent RPC facade borrowing the collector's Flexiv driver and camera streams."""

from __future__ import annotations

import argparse
import base64
import io
import json
import signal
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from robots.flexiv.motion import BoundedControl
from rpent.robots.components.env_facade_base import BaseEnvFacade


class CollectorBackend(BoundedControl):
    def __init__(
        self,
        endpoint: str,
        calibration=None,
        rgbd_dir=None,
        *,
        supervised=False,
        control_log_dir=None,
        reset_before_task=False,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.session = None
        self.connection = None
        self.calibration = calibration
        self.rgbd_dir = Path(rgbd_dir) if rgbd_dir else None
        self.supervised = supervised
        self.reset_before_task = reset_before_task
        self.control_log_dir = Path(control_log_dir) if control_log_dir else None
        self._heartbeat_stop = threading.Event()
        self._heartbeat = None

    def open(self):
        if self.connection is not None:
            raise RuntimeError("An RPent task already owns this environment")
        if self.calibration is not None and not self.supervised:
            # The existing capture route only reads an already-connected robot.
            # No collector lease or driver initialization is needed for this mode.
            observed = self.get_observation()
            self.connection = {"state": observed["state"], "motion_enabled": False}
            return {"ok": True}
        self.connection = self.request("/rpent/connect", {})
        self.session = self.connection["session"]
        if not self.supervised:
            self.connection["motion_enabled"] = False
        if self.supervised:
            self._heartbeat_stop.clear()
            self._heartbeat = threading.Thread(target=self._keepalive, daemon=True)
            self._heartbeat.start()
        return {"ok": True}

    def _keepalive(self):
        while not self._heartbeat_stop.wait(10):
            try:
                self.request("/rpent/supervised/state")
            except Exception:
                return  # Collector lease watchdog stops abandoned experiments.

    def request(self, path: str, data: dict | None = None):
        headers = {"Content-Type": "application/json"}
        if self.session:
            headers["X-RPent-Session"] = self.session
        request = Request(
            self.endpoint + path,
            data=None if data is None else json.dumps(data, allow_nan=False).encode(),
            headers=headers,
        )
        try:
            with urlopen(
                request, timeout=5 if path == "/rpent/supervised/state" else 35
            ) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Collector {exc.code}: {exc.read().decode()}") from exc

    def get_env_meta(self):
        return {
            "robot": "flexiv",
            "robot_sn": self.connection["state"]["robot_sn"],
            "coordinate_frame": "robot_base",
            "quaternion_order": "wxyz",
            "motion_enabled": self.connection["motion_enabled"],
            "max_translation_m": 0.05 if self.supervised else 0.002,
            "vla_available": False,
            "calibrated_readonly": self.calibration is not None,
            "supervised_control": self.supervised,
            "home_available": self.supervised,
            "reset_before_task": self.reset_before_task,
            "calibration_provisional": bool(
                getattr(self.calibration, "provisional", False)
            ),
        }

    def get_observation(self):
        if self.calibration is not None:
            observed = self.calibration.observation(self.rgbd_snapshot())
            if self.supervised:
                feedback = self.request("/rpent/supervised/state")
                observed["motion_enabled"] = feedback["armed"]
                observed["stop_reason"] = feedback["stop_reason"]
                observed["workspace_min"] = self.connection["workspace_min"]
                observed["workspace_max"] = self.connection["workspace_max"]
                normal, height = self.table_geometry(observed["state"])
                observed["table_normal_toward_robot"] = normal.tolist()
                observed["grasp_reference_table_clearance_m"] = height
                observed["camera_calibration"]["motion_enabled"] = feedback["armed"]
            return observed
        return self.request("/rpent/observation")

    def rgbd_snapshot(self):
        """Bracket newly acquired RGBD frames with stationary native TCP reads."""
        import numpy as np
        from PIL import Image

        if self.rgbd_dir is None:
            raise RuntimeError("Calibrated observation requires --rgbd-dir")
        before = self.calibration_snapshot()
        started = time.monotonic()
        cameras = {}
        while time.monotonic() - started < 2:
            cameras = {}
            for role in ("wrist", "side"):
                serial = self.calibration.data["camera_intrinsics"][role]["serial"]
                with np.load(
                    self.rgbd_dir / f"{serial}.npz", allow_pickle=False
                ) as bundle:
                    meta = json.loads(str(bundle["metadata"].item()))
                    if meta["serial"] != serial or meta["aligned_to"] != "color":
                        raise ValueError("RGBD snapshot identity/alignment mismatch")
                    if not started <= meta["frame_monotonic"] <= time.monotonic():
                        break
                    cameras[role] = dict(
                        meta, color_bgr=bundle["color_bgr"], depth_m=bundle["depth_m"]
                    )
            if len(cameras) == 2:
                skew = abs(
                    cameras["wrist"]["frame_monotonic"]
                    - cameras["side"]["frame_monotonic"]
                )
                acquired = time.monotonic()
                for camera in cameras.values():
                    camera["frame_age_s"] = acquired - camera["frame_monotonic"]
                if skew <= 0.15 and all(
                    0 <= camera["frame_age_s"] <= 0.15 for camera in cameras.values()
                ):
                    break
            time.sleep(0.04)
        else:
            raise RuntimeError(
                "Fresh aligned RGBD frames unavailable within two seconds"
            )
        after = self.calibration_snapshot()
        if before["tool"] != after["tool"]:
            raise ValueError("Native tool changed while acquiring RGBD")
        after["state_before"] = before["state_before"]
        after["cameras"] = {}
        for role, camera in cameras.items():
            color = camera.pop("color_bgr")
            intr = camera["intrinsics"]
            if (
                color.shape != (intr["height"], intr["width"], 3)
                or color.dtype != np.uint8
            ):
                raise ValueError("Invalid RGBD color dimensions or dtype")
            buffer = io.BytesIO()
            Image.fromarray(color[:, :, ::-1]).save(
                buffer, format="PNG", compress_level=1
            )
            camera["png_base64"] = base64.b64encode(buffer.getvalue()).decode()
            after["cameras"][self.calibration.data["board"][role]] = camera
        for camera in after["cameras"].values():
            # Keep acquisition freshness separate from HTTP/PNG delivery latency.
            camera["delivery_age_s"] = time.monotonic() - camera["frame_monotonic"]
            camera["frame_age_reference"] = (
                "RGBD acquisition, before state read/encoding"
            )
        after["synchronization"] = (
            "per-camera aligned RGBD frameset; stationary bracketing TCP; no cross-camera hardware sync"
        )
        return after

    def calibration_snapshot(self):
        # Wait for fresh, stationary feedback after a bounded physical action.
        # Rejections are retried, never converted to valid measurements.
        attempts = 8 if self.supervised else 3
        for attempt in range(attempts):
            try:
                return self.request("/calibration/snapshot")
            except RuntimeError as exc:
                message = str(exc)
                transient = message.startswith(
                    'Collector 409: {"detail":"Camera frame is stale:'
                )
                transient = transient or (
                    self.supervised
                    and message.startswith(
                        'Collector 409: {"detail":"Arm must be stationary;'
                    )
                )
                if not transient or attempt == attempts - 1:
                    raise
                time.sleep(0.2 if self.supervised else 0.05)

    def move_delta(self, xyz):
        if self.supervised:
            import numpy as np

            delta = np.asarray(xyz, float)
            if (
                delta.shape != (3,)
                or not np.isfinite(delta).all()
                or np.linalg.norm(delta) > 0.002
            ):
                raise ValueError("Delta must be finite and <=2 mm")
            state = self._control_state()
            return self.move_tcp((np.asarray(state["tcp_pose"][:3]) + delta).tolist())
        if self.calibration is not None:
            raise RuntimeError("Calibrated observation mode forbids all motion")
        return self.request("/rpent/move-delta", {"xyz": xyz})

    def close(self):
        self._heartbeat_stop.set()
        if self._heartbeat:
            self._heartbeat.join(timeout=6)
            self._heartbeat = None
        if self.session:
            try:
                self.request("/rpent/close", {})
            finally:
                self.session = None
                self.connection = None
        self.connection = None
        return {"ok": True}


class FlexivEnvFacade(BaseEnvFacade):
    def __init__(self, backend):
        self.backend = backend
        super().__init__()

    def _register_rpc(self):
        for name in ("open", "get_env_meta", "get_observation", "move_delta", "close"):
            if (
                name == "move_delta"
                and getattr(self.backend, "calibration", None) is not None
                and not getattr(self.backend, "supervised", False)
            ):
                continue
            self._rpc[f"env.{name}"] = getattr(self.backend, name)
        if getattr(self.backend, "supervised", False):
            for name in (
                "move_tcp",
                "align_tool_down",
                "set_gripper",
                "stop_motion",
                "reset_home",
            ):
                self._rpc[f"env.{name}"] = getattr(self.backend, name)
        # Motion remains serialized. The stop-only route can interrupt its owner.

    def _dispatch_nosession(self, method, args, kwargs):
        if method == "env.stop_motion" and method in self._rpc:
            return self._rpc[method](*args, **kwargs)
        return super()._dispatch_nosession(method, args, kwargs)

    def close(self):
        self.backend.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-endpoint", default="http://127.0.0.1:9527")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--calibration-file", default=None)
    parser.add_argument("--tool-tcp-file", default=None)
    parser.add_argument("--rgbd-dir", default=None)
    parser.add_argument("--supervised-control", action="store_true")
    parser.add_argument("--reset-before-task", action="store_true")
    parser.add_argument("--allow-provisional-side-control", action="store_true")
    parser.add_argument("--control-log-dir", default=None)
    parser.add_argument(
        "--allow-inconsistent-readonly",
        action="store_true",
        help="Use operator-accepted provisional calibration for read-only estimates",
    )
    args = parser.parse_args()
    if bool(args.calibration_file) != bool(args.tool_tcp_file):
        parser.error("--calibration-file and --tool-tcp-file must be supplied together")
    if bool(args.calibration_file) != bool(args.rgbd_dir):
        parser.error(
            "Calibrated observation requires --calibration-file, --tool-tcp-file and --rgbd-dir"
        )
    calibration = None
    if args.supervised_control and (
        not args.calibration_file or not args.control_log_dir
    ):
        parser.error("Supervised control requires calibration and --control-log-dir")
    if args.reset_before_task and not args.supervised_control:
        parser.error("--reset-before-task requires --supervised-control")
    if args.supervised_control and args.allow_inconsistent_readonly:
        parser.error(
            "Read-only calibration opt-in cannot enable control; use explicit side-control opt-in"
        )
    if args.allow_provisional_side_control and not args.supervised_control:
        parser.error("--allow-provisional-side-control requires --supervised-control")
    if args.allow_inconsistent_readonly and not args.calibration_file:
        parser.error("--allow-inconsistent-readonly requires a calibration file")
    if args.calibration_file:
        from robots.flexiv.perception import Calibration

        calibration = Calibration(
            args.calibration_file,
            args.tool_tcp_file,
            allow_inconsistent_readonly=args.allow_inconsistent_readonly,
            allow_provisional_side_control=args.allow_provisional_side_control,
        )
    backend = CollectorBackend(
        args.collector_endpoint,
        calibration,
        args.rgbd_dir,
        supervised=args.supervised_control,
        control_log_dir=args.control_log_dir,
        reset_before_task=args.reset_before_task,
    )
    facade = FlexivEnvFacade(backend)
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: facade._shutdown_event.set())
    try:
        facade.serve(transport="http", host=args.host, port=args.port)
    finally:
        backend.close()


if __name__ == "__main__":
    main()
