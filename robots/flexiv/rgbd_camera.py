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

"""Acquire calibrated RealSense RGB-D independently of robot control."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger(__name__)


def load_profiles(calibration_file: str | Path) -> dict[str, dict]:
    """Read the two calibrated color profiles without opening hardware."""
    data = json.loads(Path(calibration_file).expanduser().read_text())
    profiles = {role: data["camera_intrinsics"][role] for role in ("side", "wrist")}
    for profile in profiles.values():
        if not isinstance(profile["serial"], str) or not profile["serial"].isdigit():
            raise ValueError("Camera serial must be a numeric device serial")
        if any(
            type(profile[key]) is not int or profile[key] <= 0
            for key in ("width", "height", "fps")
        ):
            raise ValueError(
                "Calibrated image dimensions and FPS must be positive integers"
            )
    if profiles["side"]["serial"] == profiles["wrist"]["serial"]:
        raise ValueError("Side and wrist cameras must have distinct serials")
    return profiles


def color_intrinsics(serial: str, profile) -> dict:
    """Describe the actual active color profile using calibration field names."""
    intr = profile.as_video_stream_profile().get_intrinsics()
    return {
        "serial": serial,
        "width": intr.width,
        "height": intr.height,
        "fx": intr.fx,
        "fy": intr.fy,
        "ppx": intr.ppx,
        "ppy": intr.ppy,
        "model": str(intr.model),
        "coeffs": list(intr.coeffs),
        "fps": profile.fps(),
        "source": "active independent RealSense color profile",
    }


def frame_timing(color, depth, received_wall: float, received_monotonic: float) -> dict:
    """Keep genuine capture times and reject stale or unsynchronized pairs."""
    domains = [str(frame.get_frame_timestamp_domain()) for frame in (color, depth)]
    timestamps = [float(frame.get_timestamp()) for frame in (color, depth)]
    if domains != ["timestamp_domain.global_time"] * 2:
        raise ValueError("RGB-D timestamps have not converged to global time")
    if not np.isfinite(timestamps).all():
        raise ValueError("Nonfinite RGB-D capture timestamp")
    skew = abs(timestamps[0] - timestamps[1]) / 1000
    age = received_wall - min(timestamps) / 1000
    if skew > 0.05 or not -0.02 <= age <= 0.15:
        raise ValueError("Stale or unsynchronized RGB-D capture")
    return {
        "frame_monotonic": received_monotonic - max(0.0, age),
        "host_received_monotonic": received_monotonic,
        "host_received_s": received_wall,
        "color_timestamp_ms": timestamps[0],
        "depth_timestamp_ms": timestamps[1],
        "timestamp_domain": domains[0],
        "depth_timestamp_domain": domains[1],
        "color_depth_skew_s": skew,
        "sequence": color.get_frame_number(),
        "depth_sequence": depth.get_frame_number(),
    }


class RGBDCamera:
    """Own one camera pipeline and atomically publish its latest aligned frame."""

    def __init__(
        self,
        expected: dict,
        output_dir: str | Path,
        depth_width: int | None = None,
        depth_height: int | None = None,
    ) -> None:
        """Open the selected RealSense at its calibrated color profile."""
        import pyrealsense2 as rs

        self.serial = expected["serial"]
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()
        self._thread = None
        self.pipeline = rs.pipeline()
        if (depth_width is None) != (depth_height is None):
            raise ValueError("Specify both depth width and height")
        if depth_width is not None:
            if min(depth_width, depth_height) <= 0:
                raise ValueError("Depth dimensions must be positive")
            candidates = [(depth_width, depth_height)]
        else:
            candidates = list(
                dict.fromkeys([(640, 480), (expected["width"], expected["height"])])
            )
        for index, (width, height) in enumerate(candidates):
            config = rs.config()
            config.enable_device(self.serial)
            config.enable_stream(
                rs.stream.color,
                expected["width"],
                expected["height"],
                rs.format.bgr8,
                expected["fps"],
            )
            config.enable_stream(
                rs.stream.depth, width, height, rs.format.z16, expected["fps"]
            )
            try:
                device = config.resolve(rs.pipeline_wrapper(self.pipeline)).get_device()
                break
            except RuntimeError:
                if index == len(candidates) - 1:
                    raise
        LOGGER.info("Camera %s selected native depth %sx%s", self.serial, width, height)
        for sensor in device.query_sensors():
            if sensor.supports(rs.option.global_time_enabled):
                sensor.set_option(rs.option.global_time_enabled, 1)
            if sensor.supports(rs.option.frames_queue_size):
                sensor.set_option(rs.option.frames_queue_size, 1)
        active = self.pipeline.start(config)
        try:
            actual = color_intrinsics(self.serial, active.get_stream(rs.stream.color))
            if any(
                actual.get(key) != value
                for key, value in expected.items()
                if key != "source"
            ):
                raise ValueError(
                    f"Camera {self.serial} color profile differs from calibration"
                )
            self.scale = active.get_device().first_depth_sensor().get_depth_scale()
            if not np.isfinite(self.scale) or self.scale <= 0:
                raise ValueError("Invalid RealSense depth scale")
            self.align = rs.align(rs.stream.color)
            self._thread = threading.Thread(
                target=self._capture, daemon=True, name=f"rgbd-{self.serial}"
            )
            self._thread.start()
        except Exception:
            self.pipeline.stop()
            raise

    def _publish(self, frames, received_wall: float, received_monotonic: float) -> None:
        """Align one synchronized frameset and replace only a complete bundle."""
        color, depth = frames.get_color_frame(), frames.get_depth_frame()
        if not color or not depth:
            raise ValueError("Incomplete RGB-D frameset")
        metadata = frame_timing(color, depth, received_wall, received_monotonic)
        source_shape = list(np.asanyarray(depth.get_data()).shape)
        aligned = self.align.process(frames)
        color, depth = aligned.get_color_frame(), aligned.get_depth_frame()
        if not color or not depth:
            raise ValueError("RealSense alignment returned an incomplete frameset")
        image = np.asanyarray(color.get_data())
        depth_m = np.asanyarray(depth.get_data()).astype(np.float32) * self.scale
        intrinsics = color_intrinsics(self.serial, color.profile)
        if (
            image.shape != (intrinsics["height"], intrinsics["width"], 3)
            or image.dtype != np.uint8
        ):
            raise ValueError("Invalid color frame dimensions or dtype")
        if (
            depth_m.shape != image.shape[:2]
            or not np.isfinite(depth_m).all()
            or np.any(depth_m < 0)
        ):
            raise ValueError("Invalid color-aligned metric depth")
        metadata.update(
            serial=self.serial,
            aligned_to="color",
            depth_scale_m=self.scale,
            source_depth_shape=source_shape,
            intrinsics=intrinsics,
            producer_pid=os.getpid(),
        )
        temporary = self.output_dir / f".{self.serial}.{os.getpid()}.tmp"
        try:
            with temporary.open("wb") as handle:
                np.savez(
                    handle,
                    color_bgr=image,
                    depth_m=depth_m,
                    metadata=np.array(json.dumps(metadata, allow_nan=False)),
                )
            os.replace(temporary, self.output_dir / f"{self.serial}.npz")
        finally:
            temporary.unlink(missing_ok=True)

    def _capture(self) -> None:
        """Acquire without a processing backlog; old files remain visibly stale."""
        while not self._stop.is_set():
            try:
                frames = self.pipeline.wait_for_frames(1000)
                received_wall, received_monotonic = time.time(), time.monotonic()
                self._publish(frames, received_wall, received_monotonic)
            except ValueError as exc:
                LOGGER.debug("Camera %s rejected frame: %s", self.serial, exc)
            except (RuntimeError, OSError) as exc:
                if not self._stop.is_set():
                    LOGGER.warning("Camera %s acquisition failed: %s", self.serial, exc)
                    self._stop.wait(0.2)

    def close(self) -> None:
        """Release the camera and join its capture thread."""
        self._stop.set()
        try:
            self.pipeline.stop()
        except RuntimeError as exc:
            LOGGER.warning("Camera %s pipeline stop: %s", self.serial, exc)
        finally:
            if self._thread is not None:
                self._thread.join(timeout=3)


def main() -> None:
    """Run camera-only acquisition until SIGTERM or Ctrl-C."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--depth-width", type=int)
    parser.add_argument("--depth-height", type=int)
    args = parser.parse_args()
    if (args.depth_width is None) != (args.depth_height is None):
        parser.error("Specify both --depth-width and --depth-height")
    if args.depth_width is not None and min(args.depth_width, args.depth_height) <= 0:
        parser.error("Depth dimensions must be positive")
    logging.basicConfig(level=logging.INFO)
    profiles = load_profiles(args.calibration_file)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: stop.set())
    streams = []
    try:
        for role, profile in profiles.items():
            streams.append(
                RGBDCamera(
                    profile, args.output_dir, args.depth_width, args.depth_height
                )
            )
            LOGGER.info(
                "Independent %s camera %s publishing to %s",
                role,
                profile["serial"],
                args.output_dir,
            )
        stop.wait()
    finally:
        for stream in reversed(streams):
            stream.close()


if __name__ == "__main__":
    main()
