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

"""Read synchronized RGB-D bundles from an independent camera owner."""

import base64
import io
import json
import time


class CalibratedRGBD:
    """Shared camera-file capture; robot feedback comes from the selected backend."""

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
