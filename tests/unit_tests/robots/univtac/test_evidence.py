# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Maker export tests backed by the actual Toolkit persistence format."""

import io
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest

from robots.univtac.observations import sensor_observation
from robots.univtac.pilot.evidence import export_development
from robots.univtac.toolkit import UniVTACToolkit
from rpent.dashboard.events import NullDashboardEventSink
from rpent.memory import MemoryManager
from tests.unit_tests.robots.univtac.test_toolkit import POSE, FakeEnv


class ReceiptEnv(FakeEnv):
    def chunk_step(self, poses, *, return_all_frames):
        frames, reward, done, truncated, info = super().chunk_step(
            poses, return_all_frames=return_all_frames
        )
        info["commands"] = [
            {
                "exec_success": True,
                "native_action_delta": 1,
                "physics_step_delta": 2,
                "position_error_m": 0.001,
            }
            for _ in frames
        ]
        return frames, reward, done, truncated, info


@pytest.fixture
def recorded(tmp_path):
    root = tmp_path / "run"
    api = UniVTACToolkit(
        env=ReceiptEnv(),
        output_dir=root,
        dashboard_events=NullDashboardEventSink(),
        memory=MemoryManager(tmp_path / "memory", memory_access="read_only"),
    )
    assert not api.execute_tool("move_eef", {"poses": [POSE] * 2}).is_error
    assert not api.execute_tool("tactile_stats", {}).is_error
    assert api.execute_tool(
        "depth_points", {"camera": "head", "pixels_rc": [[99, 99]]}
    ).is_error
    yield root, api
    api.close()


def test_export_is_self_contained_and_does_not_read_private_records(
    recorded, monkeypatch
):
    root, api = recorded
    for name in ("outcome.json", "evaluator.json"):
        (root / name).write_text(
            json.dumps({"official_success": True, "actor": "ORACLE"})
        )
    (root / "native").mkdir()
    (root / "native" / "state.json").write_text("ORACLE")
    sensor_path = root / "sensor_frame.json" / "00.json"
    frame = json.loads(sensor_path.read_text())
    frame["actor"] = {"pose": "ORACLE"}
    frame["cameras"]["head"]["hidden_pose"] = "ORACLE"
    sensor_path.write_text(json.dumps(frame))
    api.journal.append(
        "tool_request", {"call_id": "stats", "name": "tactile_stats", "arguments": {}}
    )
    api.journal.append(
        "tool_response",
        {
            "call_id": "stats",
            "name": "tactile_stats",
            "result": {
                "fingers": {"left": {"mean_rgb_change": 0.1, "hole_pose": "ORACLE"}}
            },
        },
    )
    api.journal.append(
        "tool_request",
        {
            "call_id": "generated",
            "name": "sensor_probe",
            "arguments": {"radius": 3, "api_key": "never-export-this"},
        },
    )
    api.journal.append(
        "tool_response",
        {
            "call_id": "generated",
            "name": "sensor_probe",
            "result": {
                "value": 0.5,
                "margin_factor": 2,
                "official_success": True,
                "hidden_pose": "ORACLE",
                "traceback": "ORACLE",
                "nested": {"actor": "ORACLE"},
            },
        },
    )
    original_read_text, original_read_bytes = Path.read_text, Path.read_bytes

    def guard(path):
        relative = path.relative_to(root)
        assert relative.parts[0] not in {"evaluator.json", "outcome.json", "native"}

    def read_text(path, *args, **kwargs):
        guard(path)
        return original_read_text(path, *args, **kwargs)

    def read_bytes(path, *args, **kwargs):
        guard(path)
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    exported = export_development(root)
    assert set(exported) == {"sensors", "actions", "feedback"}
    with ZipFile(exported["sensors"]) as archive:
        assert json.loads(archive.read("manifest.json"))["steps"] == [0, 1, 2]
        assert all(
            name == "manifest.json" or name.startswith("frames/")
            for name in archive.namelist()
        )
        text = "".join(
            archive.read(name).decode()
            for name in archive.namelist()
            if name.endswith(".json")
        )
        assert "ORACLE" not in text and "official_success" not in text
        depth_bytes = archive.read("frames/0002/sensor_cameras_head_depth.npz")
        with np.load(io.BytesIO(depth_bytes), allow_pickle=False) as depth:
            np.testing.assert_array_equal(depth["array"], np.full((4, 6), 2.5))
    actions = json.loads(Path(exported["actions"]).read_text())["steps"]
    assert [item["step"] for item in actions] == [1, 2]
    assert actions[0]["command"] == {"action": "move_eef", "poses": [POSE] * 2}
    assert actions[1]["command_step"] == 1 and "command" not in actions[1]
    assert actions[1]["state"]["eef_pose_wxyz"] == POSE[:7]
    assert actions[1]["receipt"]["commands"][0]["physics_step_delta"] == 2
    feedback = Path(exported["feedback"]).read_text()
    assert "ORACLE" not in feedback and "official_success" not in feedback
    assert "never-export-this" not in feedback and "traceback" not in feedback
    calls = json.loads(feedback)["calls"]
    assert any(
        call["name"] == "depth_points" and call["result"].get("error") for call in calls
    )
    assert (
        calls[-1]["result"]["value"] == 0.5
        and calls[-1]["result"]["margin_factor"] == 2
    )
    (root / "sensor_cameras_head_depth.npz" / "02.npz").write_bytes(b"changed source")
    with ZipFile(exported["sensors"]) as archive:
        assert archive.read("frames/0002/sensor_cameras_head_depth.npz") == depth_bytes
    with pytest.raises(FileExistsError, match="never overwrite"):
        export_development(root)


@pytest.mark.parametrize(
    "kind", ["traversal", "cross_step", "symlink", "missing", "unlisted"]
)
def test_invalid_sensor_reference_cannot_escape_or_silently_drop_data(recorded, kind):
    root, _ = recorded
    frame_path = root / "sensor_frame.json" / "00.json"
    frame = json.loads(frame_path.read_text())
    source = root / "sensor_cameras_head_depth.npz" / "00.npz"
    if kind == "traversal":
        frame["cameras"]["head"]["depth"] = {"artifact": "../evaluator.npz"}
    elif kind == "cross_step":
        frame["step"] = 1
    elif kind == "symlink":
        source.unlink()
        source.symlink_to(root / "sensor_cameras_head_depth.npz" / "01.npz")
    elif kind == "missing":
        source.unlink()
    else:
        manifest_path = root / "states.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["steps"][0]["artifacts"].remove("sensor_cameras_head_depth.npz")
        manifest_path.write_text(json.dumps(manifest))
    frame_path.write_text(json.dumps(frame))
    with pytest.raises(ValueError):
        export_development(root)
    assert not (root / "maker-inputs").exists()


def test_no_sensor_records_fails_without_constructing_new_envstate(tmp_path):
    (tmp_path / "states.json").write_text(json.dumps({"steps": []}))
    with pytest.raises(ValueError, match="No recorded"):
        export_development(tmp_path)
    assert json.loads((tmp_path / "states.json").read_text()) == {"steps": []}


def test_initial_observation_exports_even_if_model_never_made_a_tool_call(tmp_path):
    api = UniVTACToolkit(
        env=ReceiptEnv(),
        output_dir=tmp_path / "run",
        dashboard_events=NullDashboardEventSink(),
        memory=MemoryManager(tmp_path / "memory", memory_access="read_only"),
    )
    try:
        exported = export_development(tmp_path / "run")
        assert json.loads(Path(exported["actions"]).read_text())["steps"] == []
        assert json.loads(Path(exported["feedback"]).read_text())["calls"] == []
    finally:
        api.close()


def test_tactile_export_preserves_measured_units_axes_and_distinct_resolutions(
    tmp_path,
):
    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    depth = np.full((3, 5), 1.7, dtype=np.float32)
    env = FakeEnv()
    env.last_obs = sensor_observation(
        {"tactile": {"left_tactile": {"rgb": rgb, "depth": depth}}},
        {
            "root_pose_w": {"position": [0, 0, 0], "quaternion_wxyz": [1, 0, 0, 0]},
            "hand_pose": {"position": POSE[:3], "quaternion_wxyz": POSE[3:7]},
            "gripper_qpos": 0.0195,
            "qpos": [0] * 7,
        },
        {"left": rgb.copy()},
        control_step=0,
        physics_step=0,
    )
    env.last_obs["tactile"]["left"].update(
        hidden_contact_force="ORACLE", object_pose="ORACLE", official_success=True
    )
    root = tmp_path / "run"
    api = UniVTACToolkit(
        env=env,
        output_dir=root,
        dashboard_events=NullDashboardEventSink(),
        memory=MemoryManager(tmp_path / "memory", memory_access="read_only"),
    )
    try:
        exported = export_development(root)
    finally:
        api.close()
    with ZipFile(exported["sensors"]) as archive:
        frame_text = archive.read("frames/0000/sensor_frame.json").decode()
        assert "ORACLE" not in frame_text and "official_success" not in frame_text
        tactile = json.loads(frame_text)["tactile"]
        expected = {
            "image_size": [4, 6],
            "depth_image_size": [3, 5],
            "depth_units": "mm",
            "depth_semantics": "native_sensor_camera_depth_not_indentation",
            "marker_units": "pixels",
            "marker_coordinate_order": "x,y",
            "marker_origin": "top_left",
            "marker_axes": "x_right_y_down",
            "reference_kind": "episode_initial_contact",
            "tracking_quality": None,
        }
        assert {key: tactile["left"][key] for key in expected} == expected
        for key in ("depth", "depth_units", "depth_image_size", "depth_semantics"):
            assert key not in tactile["right"]
        with np.load(
            io.BytesIO(archive.read("frames/0000/sensor_tactile_left_depth.npz")),
            allow_pickle=False,
        ) as saved:
            np.testing.assert_array_equal(saved["array"], depth)
