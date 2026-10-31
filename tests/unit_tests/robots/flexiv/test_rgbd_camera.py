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

"""Independent RGB-D ownership and publication tests without camera hardware."""

import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from robots.flexiv.rgbd_camera import RGBDCamera, frame_timing, load_profiles, main


def frame(data, timestamp=100000.0, domain="timestamp_domain.global_time", sequence=1):
    intr = SimpleNamespace(
        width=4,
        height=3,
        fx=5,
        fy=6,
        ppx=2,
        ppy=1,
        model="distortion.none",
        coeffs=[0.0] * 5,
    )
    profile = SimpleNamespace(
        fps=lambda: 30,
        as_video_stream_profile=lambda: SimpleNamespace(get_intrinsics=lambda: intr),
    )
    return SimpleNamespace(
        get_data=lambda: data,
        get_timestamp=lambda: timestamp,
        get_frame_timestamp_domain=lambda: domain,
        get_frame_number=lambda: sequence,
        profile=profile,
    )


def frameset(color, depth):
    return SimpleNamespace(get_color_frame=lambda: color, get_depth_frame=lambda: depth)


def writer(tmp_path, aligned):
    camera = RGBDCamera.__new__(RGBDCamera)
    camera.serial, camera.output_dir, camera.scale = "123", tmp_path, 0.001
    camera.align = SimpleNamespace(process=lambda frames: aligned)
    return camera


def test_capture_age_is_not_reset_at_file_publication():
    color = frame(None, timestamp=99980)
    depth = frame(None, timestamp=99970)
    metadata = frame_timing(color, depth, 100.0, 20.0)
    assert metadata["frame_monotonic"] == pytest.approx(19.97)
    assert metadata["host_received_monotonic"] == 20.0
    assert metadata["color_depth_skew_s"] == pytest.approx(0.01)
    assert metadata["color_timestamp_ms"] == 99980
    assert metadata["depth_timestamp_ms"] == 99970


@pytest.mark.parametrize(
    "color,depth",
    [
        (frame(None, domain="timestamp_domain.hardware_clock"), frame(None)),
        (frame(None), frame(None, domain="timestamp_domain.hardware_clock")),
        (frame(None, timestamp=99000), frame(None, timestamp=99000)),
        (frame(None, timestamp=100100), frame(None, timestamp=100100)),
        (frame(None, timestamp=99900), frame(None)),
        (frame(None, timestamp=float("nan")), frame(None)),
    ],
)
def test_reject_bad_time_pair(color, depth):
    with pytest.raises(ValueError):
        frame_timing(color, depth, 100.0, 20.0)


def test_publish_preserves_color_native_depth_resolution_and_metric_units(tmp_path):
    color_data = np.full((3, 4, 3), [1, 2, 3], dtype=np.uint8)
    color = frame(color_data, sequence=8)
    source = frameset(color, frame(np.ones((2, 2), dtype=np.uint16), sequence=6))
    aligned = frameset(color, frame(np.full((3, 4), 250, dtype=np.uint16)))
    camera = writer(tmp_path, aligned)
    camera._publish(source, 100.0, 20.0)
    with np.load(tmp_path / "123.npz", allow_pickle=False) as bundle:
        np.testing.assert_array_equal(bundle["color_bgr"], color_data)
        np.testing.assert_array_equal(
            bundle["depth_m"], np.full((3, 4), 0.25, dtype=np.float32)
        )
        metadata = json.loads(str(bundle["metadata"].item()))
    assert metadata["source_depth_shape"] == [2, 2]
    assert metadata["aligned_to"] == "color"
    assert metadata["intrinsics"]["width"] == 4
    assert metadata["intrinsics"]["fx"] == 5
    assert (metadata["sequence"], metadata["depth_sequence"]) == (8, 6)


def test_failed_write_keeps_previous_complete_bundle(tmp_path, monkeypatch):
    color = frame(np.zeros((3, 4, 3), dtype=np.uint8))
    frames = frameset(color, frame(np.zeros((3, 4), dtype=np.uint16)))
    camera = writer(tmp_path, frames)
    camera._publish(frames, 100.0, 20.0)
    path = tmp_path / "123.npz"
    old = path.read_bytes()

    def fail(handle, **kwargs):
        handle.write(b"partial")
        raise OSError("Disk full")

    monkeypatch.setattr(np, "savez", fail)
    with pytest.raises(OSError, match="Disk full"):
        camera._publish(frames, 100.0, 21.0)
    assert path.read_bytes() == old
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize(
    "bad_depth", [np.zeros((2, 2)), np.full((3, 4), float("nan")), np.full((3, 4), -1)]
)
def test_reject_unaligned_or_invalid_depth_without_publishing(tmp_path, bad_depth):
    color = frame(np.zeros((3, 4, 3), dtype=np.uint8))
    frames = frameset(color, frame(bad_depth))
    camera = writer(tmp_path, frames)
    with pytest.raises(ValueError, match="metric depth"):
        camera._publish(frames, 100.0, 20.0)
    assert not list(tmp_path.iterdir())


def test_camera_profiles_are_read_only_calibration_inputs(tmp_path):
    path = tmp_path / "calibration.json"
    side = {"serial": "123", "width": 1280, "height": 720, "fps": 30}
    wrist = dict(side, serial="456")
    path.write_text(json.dumps({"camera_intrinsics": {"side": side, "wrist": wrist}}))
    assert load_profiles(path) == {"side": side, "wrist": wrist}
    wrist["serial"] = side["serial"]
    path.write_text(json.dumps({"camera_intrinsics": {"side": side, "wrist": wrist}}))
    with pytest.raises(ValueError, match="distinct"):
        load_profiles(path)


def test_mismatched_active_color_profile_releases_camera(tmp_path, monkeypatch):
    calls = []
    device = SimpleNamespace(query_sensors=lambda: [])
    active = SimpleNamespace(get_stream=lambda stream: frame(None).profile)
    pipeline = SimpleNamespace(
        start=lambda config: active, stop=lambda: calls.append("stop")
    )
    config = SimpleNamespace(
        enable_device=lambda serial: None,
        enable_stream=lambda *args: None,
        resolve=lambda wrapper: SimpleNamespace(get_device=lambda: device),
    )
    sdk = SimpleNamespace(
        pipeline=lambda: pipeline,
        pipeline_wrapper=lambda pipe: pipe,
        config=lambda: config,
        stream=SimpleNamespace(color="color", depth="depth"),
        format=SimpleNamespace(bgr8="bgr8", z16="z16"),
    )
    monkeypatch.setitem(sys.modules, "pyrealsense2", sdk)
    expected = {"serial": "123", "width": 4, "height": 3, "fps": 30, "fx": 123}
    with pytest.raises(ValueError, match="differs from calibration"):
        RGBDCamera(expected, tmp_path)
    assert calls == ["stop"]


@pytest.mark.parametrize("explicit", [False, True])
def test_depth_selection_resolves_before_start_and_does_not_override_explicit_profile(
    tmp_path, monkeypatch, explicit
):
    calls = []
    device = SimpleNamespace(
        query_sensors=lambda: [],
        first_depth_sensor=lambda: SimpleNamespace(get_depth_scale=lambda: 0.001),
    )
    color_profile = frame(None).profile
    intrinsics = color_profile.as_video_stream_profile().get_intrinsics()
    intrinsics.width, intrinsics.height = 1280, 720
    active = SimpleNamespace(
        get_stream=lambda stream: color_profile, get_device=lambda: device
    )

    class Config:
        def enable_device(self, serial):
            pass

        def enable_stream(self, stream, width, height, format, fps):
            if stream == "depth":
                self.depth_size = (width, height)

        def resolve(self, pipeline):
            calls.append(("resolve", self.depth_size))
            if self.depth_size == (640, 480):
                raise RuntimeError("No compatible profile")
            return SimpleNamespace(get_device=lambda: device)

    def start(config):
        calls.append(("start", config.depth_size))
        return active

    pipeline = SimpleNamespace(start=start, stop=lambda: calls.append("stop"))
    sdk = SimpleNamespace(
        pipeline=lambda: pipeline,
        pipeline_wrapper=lambda pipe: pipe,
        config=Config,
        align=lambda stream: None,
        stream=SimpleNamespace(color="color", depth="depth"),
        format=SimpleNamespace(bgr8="bgr8", z16="z16"),
    )
    monkeypatch.setitem(sys.modules, "pyrealsense2", sdk)
    monkeypatch.setattr(
        "robots.flexiv.rgbd_camera.threading.Thread",
        lambda **kwargs: SimpleNamespace(start=lambda: None, join=lambda timeout: None),
    )
    expected = {"serial": "123", "width": 1280, "height": 720, "fps": 30}
    if explicit:
        with pytest.raises(RuntimeError, match="No compatible profile"):
            RGBDCamera(expected, tmp_path, 640, 480)
        assert calls == [("resolve", (640, 480))]
    else:
        camera = RGBDCamera(expected, tmp_path)
        camera.close()
        assert calls == [
            ("resolve", (640, 480)),
            ("resolve", (1280, 720)),
            ("start", (1280, 720)),
            "stop",
        ]


def test_cli_requires_both_explicit_depth_dimensions(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rgbd_camera",
            "--calibration-file",
            "unused",
            "--output-dir",
            "unused",
            "--depth-width",
            "640",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "Specify both" in capsys.readouterr().err
