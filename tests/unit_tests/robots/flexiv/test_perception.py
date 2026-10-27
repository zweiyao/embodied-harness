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

"""Offline RGBD and observer-only contracts; never instantiate hardware."""

import base64
import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from robots.flexiv.env_server import CollectorBackend, FlexivEnvFacade
from robots.flexiv.perception import Calibration, back_project
from robots.flexiv.toolkit import FlexivToolkit


@pytest.fixture
def scene(tmp_path):
    intr = {
        "serial": "test",
        "width": 100,
        "height": 80,
        "fx": 100.0,
        "fy": 100.0,
        "ppx": 50.0,
        "ppy": 40.0,
        "model": "distortion.none",
        "coeffs": [0.0] * 5,
        "fps": 30,
    }
    tool = {"name": "test-tool", "tcp_location": [0, 0, 0.19, 1, 0, 0, 0]}
    calibration = {
        "tool": tool,
        "robot_sn": "test-robot",
        "board": {"wrist": "w", "side": "s"},
        "camera_intrinsics": {"wrist": intr, "side": intr},
        "wrist_consistency_passed": True,
        "side_consistency_passed": True,
        "T_tcp_wrist_camera": np.eye(4).tolist(),
        "T_base_side_camera": np.eye(4).tolist(),
        "T_base_board": np.eye(4).tolist(),
    }
    compensation = {
        "native_tool": tool,
        "tcp_to_grasp_translation_m": [0, 0, 0.00837],
        "coordinate_frame": "native_tool_tcp",
        "rotation_offset": "identity",
    }
    files = [tmp_path / "cal.json", tmp_path / "tcp.json"]
    for path, data in zip(files, (calibration, compensation)):
        path.write_text(json.dumps(data))
    model = Calibration(*files)
    buffer = io.BytesIO()
    Image.new("RGB", (100, 80)).save(buffer, format="PNG")
    state = {
        "robot_sn": "test-robot",
        "coordinate_frame": "robot_base",
        "quaternion_order": "wxyz",
        "tcp_pose": [0.2, 0, 0, 1, 0, 0, 0],
        "joint_velocity": [0.0] * 7,
        "fault": False,
    }
    camera = {
        "intrinsics": intr,
        "png_base64": base64.b64encode(buffer.getvalue()).decode(),
        "frame_age_s": 0.02,
        "frame_monotonic": 100.0,
        "timestamp_domain": "timestamp_domain.global_time",
        "color_depth_skew_s": 0.0,
        "aligned_to": "color",
        "depth_m": np.full((80, 100), 0.5, dtype=np.float32),
    }
    snapshot = {
        "tool": tool,
        "state_before": copy.deepcopy(state),
        "state_after": copy.deepcopy(state),
        "cameras": {"w": copy.deepcopy(camera), "s": copy.deepcopy(camera)},
        "captured_at": 1.0,
        "synchronization": "synthetic",
    }
    return model, snapshot


def test_known_geometry_and_compensation(scene):
    model, snapshot = scene
    obs = model.observation(snapshot)
    result = back_project(
        obs["camera_calibration"],
        obs["depths"]["wrist"],
        "wrist",
        [50, 40],
        [10, 10, 90, 70],
    )
    np.testing.assert_allclose(result["point_base_m"], [0.2, 0, 0.5])
    np.testing.assert_allclose(
        result["native_tcp_if_this_point_is_grasp_reference_m"], [0.2, 0, 0.49163]
    )
    assert not result["motion_authorized"]


def test_provisional_calibration_is_explicit_and_readonly(scene):
    model, snapshot = scene
    calibration_file, tool_file = model.hashes
    data = json.loads(Path(calibration_file).read_text())
    data["wrist_consistency_passed"] = False
    Path(calibration_file).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="consistency"):
        Calibration(calibration_file, tool_file)
    provisional = Calibration(
        calibration_file, tool_file, allow_inconsistent_readonly=True
    )
    obs = provisional.observation(snapshot)
    result = back_project(
        obs["camera_calibration"],
        obs["depths"]["side"],
        "side",
        [50, 40],
        [10, 10, 90, 70],
    )
    assert result["calibration_validation"] == {
        "wrist_passed": False,
        "side_passed": True,
        "provisional_readonly": True,
        "provisional": True,
        "control_camera": None,
    }
    assert not result["motion_authorized"] and not obs["motion_enabled"]
    snapshot["state_after"]["fault"] = True
    with pytest.raises(ValueError, match="fault"):
        provisional.observation(snapshot)


@pytest.mark.parametrize(
    "fault",
    ["stale", "profile", "tool", "moving", "nan", "alignment", "shape", "time_skew"],
)
def test_reject_bad_capture(scene, fault):
    model, snapshot = scene
    if fault == "stale":
        snapshot["cameras"]["w"]["frame_age_s"] = 0.5
    if fault == "time_skew":
        snapshot["cameras"]["w"]["color_depth_skew_s"] = 0.133
    if fault == "profile":
        snapshot["cameras"]["w"]["intrinsics"]["serial"] = "other"
    if fault == "tool":
        snapshot["tool"] = {"name": "other"}
    if fault == "moving":
        snapshot["state_after"]["tcp_pose"][0] += 0.001
    if fault == "nan":
        snapshot["state_after"]["tcp_pose"][0] = float("nan")
    if fault == "alignment":
        snapshot["cameras"]["w"]["aligned_to"] = "depth"
    if fault == "shape":
        snapshot["cameras"]["w"]["depth_m"] = np.ones((2, 2))
    with pytest.raises(ValueError):
        model.observation(snapshot)


@pytest.mark.parametrize("fault", ["zero", "nan", "edge", "clipped", "outside"])
def test_reject_bad_pixel(scene, fault):
    model, snapshot = scene
    obs = model.observation(snapshot)
    depth = obs["depths"]["side"].copy()
    box, pixel = [10, 10, 90, 70], [50, 40]
    if fault == "zero":
        depth[40, 50] = 0
    if fault == "nan":
        depth[40, 50] = float("nan")
    if fault == "edge":
        depth[38:43, 50:53] = 1
    if fault == "clipped":
        box[0] = 0
    if fault == "outside":
        pixel[0] = 99
    with pytest.raises(ValueError):
        back_project(obs["camera_calibration"], depth, "side", pixel, box)


def test_calibrated_backend_never_connects_or_registers_motion(scene, monkeypatch):
    model, snapshot = scene
    backend = CollectorBackend("http://unused", model, "/unused")
    monkeypatch.setattr(backend, "rgbd_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        backend,
        "request",
        lambda *a, **kw: pytest.fail("Unexpected collector control call"),
    )
    backend.open()
    assert backend.get_env_meta()["motion_enabled"] is False
    assert "env.move_delta" not in FlexivEnvFacade(backend)._rpc
    with pytest.raises(RuntimeError, match="forbids"):
        backend.move_delta([0.001, 0, 0])
    backend.close()


@pytest.mark.parametrize("capture_tool", ["observe", "move_tcp"])
def test_tool_saves_depth_and_uses_exact_step(
    scene, tmp_path, monkeypatch, capture_tool
):
    model, snapshot = scene
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda x: x)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    env = SimpleNamespace(
        meta={
            "calibrated_readonly": True,
            "motion_enabled": capture_tool == "move_tcp",
            "supervised_control": True,
        },
        get_observation=lambda: model.observation(snapshot),
        move_tcp=lambda position_m, quaternion_wxyz: {"reached": True},
        close=lambda: None,
    )
    kit = FlexivToolkit(
        env=env,
        output_dir=tmp_path / "run",
        memory=SimpleNamespace(),
        dashboard_events=SimpleNamespace(enabled=False, emit=lambda x: None),
    )
    expected_tools = {
        "observe",
        "view_perception_setup",
        "localize_target",
    }
    if capture_tool == "move_tcp":
        expected_tools |= {
            "move_delta",
            "move_tcp",
            "align_tool_down",
            "set_gripper",
            "stop_motion",
        }
    assert {t.name for t in kit.list_tools()} == expected_tools
    captured = kit.execute_tool(
        capture_tool, {} if capture_tool == "observe" else {"position_m": [0.2, 0, 0]}
    )
    assert not captured.is_error
    assert len(captured.images) == 2
    summary = captured.data["camera_calibration"]
    assert "state" not in summary
    assert "source_sha256" not in summary
    assert summary["cameras"]["side"]["image_size"] == [100, 80]
    assert "intrinsics" not in summary["cameras"]["side"]
    assert "T_base_camera" not in summary["cameras"]["side"]
    full = kit.execute_tool("view_perception_setup", {"step": captured.data["step"]})
    assert full.data == model.observation(snapshot)["camera_calibration"]
    assert summary["calibration_validation"] == full.data["calibration_validation"]
    assert summary["grasp_reference_base_m"] == full.data["grasp_reference_base_m"]
    assert summary["cameras"]["side"]["frame_age_s"] == 0.02
    result = kit.execute_tool(
        "localize_target",
        {
            "step": 0,
            "target": "test surface",
            "camera": "side",
            "pixel": [50, 40],
            "box": [10, 10, 90, 70],
        },
    )
    assert result.data["source"] == "color_aligned_realsense_depth"
    assert result.data["step"] == 0
    assert len(result.images) == 1
    assert kit.state.exists("side_depth.npy", step=0)
    kit.close()


@pytest.mark.parametrize("stale", [True, False])
def test_snapshot_retries_only_transient_staleness(monkeypatch, stale):
    backend = CollectorBackend("http://unused")
    calls = []
    message = (
        'Collector 409: {"detail":"Camera frame is stale: wrist"}'
        if stale
        else 'Collector 409: {"detail":"Robot reports a fault"}'
    )

    def request(path):
        calls.append(path)
        raise RuntimeError(message)

    monkeypatch.setattr(backend, "request", request)
    monkeypatch.setattr("robots.flexiv.env_server.time.sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="Collector 409"):
        backend.calibration_snapshot()
    assert len(calls) == (3 if stale else 1)


def test_control_requires_explicit_side_validation(scene):
    model, snapshot = scene
    calibration_file, tool_file = model.hashes
    data = json.loads(Path(calibration_file).read_text())
    data["wrist_consistency_passed"] = False
    Path(calibration_file).write_text(json.dumps(data))
    controlled = Calibration(
        calibration_file, tool_file, allow_provisional_side_control=True
    )
    assert controlled.provisional and not controlled.provisional_readonly
    assert not controlled.data["wrist_consistency_passed"]
    data["side_consistency_passed"] = False
    Path(calibration_file).write_text(json.dumps(data))
    with pytest.raises(ValueError):
        Calibration(calibration_file, tool_file, allow_provisional_side_control=True)


def test_operator_confirmation_preserves_history_and_binds_file(scene, monkeypatch):
    model, snapshot = scene
    calibration_file, tool_file = model.hashes
    path = Path(calibration_file)
    data = json.loads(path.read_text())
    data["wrist_consistency_passed"] = False
    path.write_text(json.dumps(data))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    confirmed = Calibration(
        calibration_file,
        tool_file,
        allow_provisional_side_control=True,
        operator_confirmed_calibration_sha256=digest,
    )
    validation = confirmed.observation(snapshot)["camera_calibration"][
        "calibration_validation"
    ]
    assert validation["operator_confirmed_cameras"] == ["side", "wrist"]
    assert not validation["wrist_passed"]
    assert validation["operator_confirmation"]["calibration_sha256"] == digest
    assert validation["operator_confirmation"]["measured_error_mm"] is None
    backend = CollectorBackend("http://unused", confirmed, "/unused")
    monkeypatch.setattr(backend, "rgbd_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        backend, "request", lambda *a, **kw: pytest.fail("Unexpected request")
    )
    backend.open()
    assert backend.get_env_meta()["operator_confirmed_cameras"] == ["side", "wrist"]
    assert not backend.get_env_meta()["motion_enabled"]
    with pytest.raises(ValueError, match="supervised side control"):
        Calibration(
            calibration_file, tool_file, operator_confirmed_calibration_sha256=digest
        )
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="SHA256"):
        Calibration(
            calibration_file,
            tool_file,
            allow_provisional_side_control=True,
            operator_confirmed_calibration_sha256=digest,
        )


@pytest.mark.parametrize("confirmed", [False, True])
def test_wrist_localization_requires_operator_confirmation_in_provisional_control(
    scene, tmp_path, monkeypatch, confirmed
):
    model, snapshot = scene
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda x: x)
    monkeypatch.setattr(FlexivToolkit, "_register_common_tools", lambda self: None)
    env = SimpleNamespace(
        meta={
            "calibrated_readonly": True,
            "motion_enabled": True,
            "calibration_provisional": True,
            "operator_confirmed_cameras": ["side", "wrist"] if confirmed else [],
        },
        get_observation=lambda: model.observation(snapshot),
        close=lambda: None,
    )
    kit = FlexivToolkit(
        env=env,
        output_dir=tmp_path / "run",
        memory=SimpleNamespace(),
        dashboard_events=SimpleNamespace(enabled=False, emit=lambda x: None),
    )
    result = kit.execute_tool(
        "localize_target",
        {
            "step": 0,
            "target": "surface",
            "camera": "wrist",
            "pixel": [50, 40],
            "box": [10, 10, 90, 70],
        },
    )
    assert result.is_error is not confirmed
    if confirmed:
        assert result.data["camera"] == "wrist"
        assert not result.data["motion_authorized"]
    kit.close()
