# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Offline sensor isolation, selection and episode accounting contracts."""

import copy
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from robots.libero.research.library import digest
from robots.univtac import toolkit as module
from robots.univtac.control import native_status
from robots.univtac.observations import sensor_observation
from robots.univtac.perception import tactile_statistics
from rpent.dashboard.events import NullDashboardEventSink
from rpent.memory import MemoryManager

POSE = [0.1, 0.2, 0.3, 1.0, 0.0, 0.0, 0.0, 0.5]


def observation(step=0):
    rgb = np.full((4, 6, 3), step, dtype=np.uint8)
    native = {
        "observation": {"head": {"rgb": rgb, "depth": np.full((4, 6), 0.5 + step)}},
        "tactile": {
            "left_tactile": {
                "rgb": rgb.copy(),
                "marker": np.array(
                    [[[0.0, 0.0], [0.0, 0.0]], [[3.0, 4.0], [np.nan, 0.0]]]
                ),
            }
        },
    }
    robot_state = {
        "root_pose_w": {"position": [0, 0, 0], "quaternion_wxyz": [1, 0, 0, 0]},
        "hand_pose": {"position": POSE[:3], "quaternion_wxyz": POSE[3:7]},
        "gripper_qpos": 0.0195,
        "qpos": [0] * 7 + [0.0195],
    }
    frame = sensor_observation(
        native,
        robot_state,
        {"left": np.zeros_like(rgb)},
        control_step=step,
        physics_step=step * 2,
        calibration={
            "head": {
                "depth_units": "m",
                "intrinsics": np.eye(3),
                "position_w": np.zeros(3),
                "quaternion_wxyz": np.array([1, 0, 0, 0]),
                "camera_convention": "ros_optical",
                "height": 4,
                "width": 6,
            }
        },
    )
    frame["actor"] = {"hidden_hole_pose": "private_actor"}
    frame["evaluator"] = {"official_success": True}
    return frame


class FakeEnv:
    def __init__(self, *, end_after=None, success=False):
        self.last_obs = observation()
        self.count = 0
        self.chunk_calls = []
        self.end_after = end_after
        self.success = success
        self.closed = False

    def get_observation(self):
        return self.last_obs

    def chunk_step(self, poses, *, return_all_frames):
        assert return_all_frames is True
        self.chunk_calls.append(copy.deepcopy(poses))
        frames = []
        for _ in poses:
            self.count += 1
            self.last_obs = observation(self.count)
            frames.append(self.last_obs)
            if self.end_after is not None and self.count >= self.end_after:
                break
        ended = self.end_after is not None and self.count >= self.end_after
        return frames, 0.0, ended, False, {"executed_commands": len(frames)}

    def evaluator_state(self):
        done = self.end_after is not None and self.count >= self.end_after
        task = SimpleNamespace(
            eval_success=self.success and done,
            check_early_stop=lambda: done and not self.success,
            take_action_cnt=self.count,
            cfg=SimpleNamespace(step_lim=300),
            plan_success=True,
        )
        return {
            **native_status(task),
            "scene": {"actor": "private_evaluator"},
        }

    def close(self):
        self.closed = True


@pytest.fixture
def create_toolkit(tmp_path, monkeypatch):
    monkeypatch.setattr("rpent.utils.templates.get_output_dir", lambda: tmp_path)
    opened = []

    def create(*, env=None, selected=None):
        api = module.UniVTACToolkit(
            env=env or FakeEnv(),
            output_dir=tmp_path / f"run-{len(opened)}",
            dashboard_events=NullDashboardEventSink(),
            memory=MemoryManager(tmp_path / "memory", memory_access="read_only"),
            selected=selected,
        )
        opened.append(api)
        return api

    yield create
    for api in opened:
        api.close()


def test_catalog_and_execution_use_the_same_selected_allowlist(create_toolkit):
    catalog = module.native_catalog()
    complete = create_toolkit()
    assert {t.name: t.input_schema for t in complete.list_tools()} == {
        t["name"]: t["parameters"] for t in catalog
    }
    selected = [t for t in catalog if t["name"] in {"finish", "observe"}]
    restricted = create_toolkit(selected=selected)
    assert {t.name for t in restricted.list_tools()} == {"finish", "observe"}
    assert restricted.execute_tool("move_eef", {"poses": [POSE]}).is_error
    assert restricted.execute_tool("tactile_stats", {}).is_error
    assert not restricted.env.chunk_calls


@pytest.mark.parametrize("field", ["version", "source", "parameters", "description"])
def test_native_selection_cannot_silently_use_a_changed_definition(
    create_toolkit, field
):
    selected = copy.deepcopy(module.native_catalog())
    target = next(item for item in selected if item["name"] == "move_eef")
    target[field] = {"type": "object"} if field == "parameters" else "stale"
    with pytest.raises(ValueError, match="changed since selection: move_eef"):
        create_toolkit(selected=selected)


def test_model_cannot_read_evaluator_files_or_write_memory(create_toolkit):
    api = create_toolkit()
    for name, params in [
        ("read_text_file", {"path": str(api.journal.root / "evaluator.json")}),
        ("write_text_file", {"path": "memory.md", "text": "success"}),
        ("list_dir", {}),
        ("evaluator_state", {}),
        ("read_image", {"name": "evaluator.json"}),
    ]:
        assert api.execute_tool(name, params).is_error
    with pytest.raises(PermissionError):
        api.memory.authorize_write(api.memory.root / "MEMORY.md")


def test_recorded_images_depth_and_tactile_round_trip_without_privileged_fields(
    create_toolkit,
):
    api = create_toolkit()
    original = copy.deepcopy(api.env.last_obs)
    api.env.last_obs["cameras"]["head"]["rgb"][:] = 250
    frame = api._frame(0)
    assert "actor" not in frame and "evaluator" not in frame
    np.testing.assert_array_equal(
        frame["cameras"]["head"]["rgb"], original["cameras"]["head"]["rgb"]
    )
    result = api.execute_tool("observe", {})
    assert len(result.images) == 2  # camera and tactile, not the reference image
    assert "private_" not in result.to_text()
    assert "official_success" not in result.to_text()
    assert result.data["state"]["eef_pose_wxyz"] == POSE[:7]
    assert result.data["state"]["joint_positions"] == [0] * 7
    depth = api.execute_tool(
        "depth_points", {"camera": "head", "pixels_rc": [[0, 0], [3, 5]]}
    )
    assert depth.data["depth_m"] == [0.5, 0.5]
    assert (
        json.loads(depth.to_text())["calibration"]["intrinsics"] == np.eye(3).tolist()
    )
    reference = api.execute_tool(
        "read_image", {"name": "sensor_tactile_left_reference_rgb.png", "step": 0}
    )
    assert len(reference.images) == 1 and not reference.is_error
    saved = json.loads((api.journal.root / "evaluator.json").read_text())
    assert saved["scene"]["actor"] == "private_evaluator"


def test_float_tactile_previews_reach_model_and_keep_raw_arrays(create_toolkit):
    env = FakeEnv()
    raw = np.tile(
        np.array([0, 0.49, 0.51, 128.25, 254.75, 255], dtype=np.float32)[None, :, None],
        (4, 1, 3),
    )
    for side, image in (("left", raw), ("right", raw[:, ::-1].copy())):
        env.last_obs["tactile"][side] = {
            "rgb": image,
            "reference_rgb": image.copy(),
            "reference_kind": "episode_initial_contact",
        }
    api = create_toolkit(env=env)
    observed = api.execute_tool("observe", {})
    assert set(observed.data["images"]) == {
        "sensor_cameras_head_rgb.png",
        "sensor_tactile_left_rgb.png",
        "sensor_tactile_right_rgb.png",
    }
    assert len(observed.images) == 3
    for side in ("left", "right"):
        original = env.last_obs["tactile"][side]["rgb"]
        recorded = api._frame(0)["tactile"][side]["rgb"]
        assert recorded.dtype == np.float32
        np.testing.assert_array_equal(recorded, original)
        for kind in ("rgb", "reference_rgb"):
            name = f"sensor_tactile_{side}_{kind}.png"
            result = api.execute_tool("read_image", {"name": name, "step": 0})
            assert not result.is_error and len(result.images) == 1
            preview = np.asarray(Image.open(io.BytesIO(result.images[0])))
            np.testing.assert_array_equal(preview, np.rint(original).astype(np.uint8))
            metadata = result.data["image_metadata"]
            assert metadata["source_artifact"] == name.removesuffix(".png") + ".npz"
            assert metadata["source_dtype"] == "float32"
            assert metadata["source_range"] == [0, 255]
            assert metadata["encoding"] == "RGB8 PNG"
            assert metadata["clipped_values"] == 0
    # The same recorded image result is appended after each stateful command.
    env.chunk_step = lambda poses, **kw: (
        [env.last_obs],
        0.0,
        False,
        False,
        {"executed_commands": 1},
    )
    moved = api.execute_tool("move_eef", {"poses": [POSE]})
    assert not moved.is_error and len(moved.images) == 3


def test_invalid_tactile_image_is_recorded_without_invented_preview(create_toolkit):
    env = FakeEnv()
    env.last_obs["tactile"]["left"]["rgb"] = np.full((4, 6, 3), np.nan, np.float32)
    api = create_toolkit(env=env)
    result = api.execute_tool("observe", {})
    assert "sensor_tactile_left_rgb.png" not in result.data["images"]
    assert np.isnan(api._frame(0)["tactile"]["left"]["rgb"]).all()
    metadata = result.data["sensors"]["image_previews"]["sensor_tactile_left_rgb.png"]
    assert "unavailable" in metadata["error"]


def test_generated_program_gets_last_four_independent_sensor_frames(
    create_toolkit, monkeypatch
):
    captured = []

    class FakeSandbox:
        image = "offline-image"

        def __init__(self, image):
            pass

        def run(self, definition, params, frames):
            captured.append(copy.deepcopy(frames))
            frames[-1]["cameras"]["head"]["depth"][:] = 999
            return {"observed_steps": [f["step"] for f in frames]}

    monkeypatch.setattr(module, "Sandbox", FakeSandbox)
    generated = {
        "id": "generated:sensor_probe",
        "name": "sensor_probe",
        "origin": "generated",
        "description": "Probe recorded sensors",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "source": "def run(frames, params): return {}",
    }
    generated["version"] = digest(
        [
            {
                key: generated[key]
                for key in ("name", "description", "parameters", "source")
            }
        ]
    )
    api = create_toolkit(selected=[*module.native_catalog(), generated])
    assert not api.execute_tool("move_eef", {"poses": [POSE] * 5}).is_error
    result = api.execute_tool("sensor_probe", {})
    assert result.data["observed_steps"] == [2, 3, 4, 5]
    assert all("actor" not in f and "evaluator" not in f for f in captured[0])
    assert api._frame(5)["cameras"]["head"]["depth"][0, 0] == 5.5
    assert json.loads((api.journal.root / "tool-invocations.json").read_text()) == [
        generated["version"]
    ]


@pytest.mark.parametrize("poses", [[], [POSE] * 6, "not-a-pose-list"])
def test_invalid_action_batches_are_logged_and_do_not_advance_physics(
    create_toolkit, poses
):
    api = create_toolkit()
    result = api.execute_tool("move_eef", {"poses": poses})
    assert result.is_error
    assert not api.env.chunk_calls and api.env.count == 0
    events = [
        json.loads(line)
        for line in (api.journal.root / "events.jsonl").read_text().splitlines()
    ]
    assert len([e for e in events if e["kind"] == "tool_request"]) == 1
    responses = [e["payload"] for e in events if e["kind"] == "tool_response"]
    assert len(responses) == 1 and responses[0]["result"]["error"]


def test_official_terminal_state_stops_actions_without_success_leak(create_toolkit):
    env = FakeEnv(end_after=1, success=True)
    api = create_toolkit(env=env)
    result = api.execute_tool("move_eef", {"poses": [POSE] * 5})
    assert api.solved() and api.planner_stop_result["_finish"]
    assert env.count == 1
    assert (
        "official_success" not in result.to_text()
        and "private_" not in result.to_text()
    )
    assert api.execute_tool("move_eef", {"poses": [POSE]}).is_error
    assert len(env.chunk_calls) == 1


def test_evaluator_status_contract_uses_official_field(create_toolkit):
    api = create_toolkit(env=FakeEnv(end_after=0, success=True))
    evaluator = json.loads((api.journal.root / "evaluator.json").read_text())
    assert evaluator["official_success"] is True
    assert "native_success" not in evaluator
    assert api.solved()


def test_model_finish_success_does_not_replace_official_evaluator(create_toolkit):
    api = create_toolkit()
    finish = api.execute_tool(
        "finish", {"status": "success", "summary": "I think it is done"}
    )
    assert finish.data["_finish"] and api.planner_stop_result["_finish"]
    assert not api.solved()
    assert api.execute_tool("move_eef", {"poses": [POSE]}).is_error
    assert not api.env.chunk_calls


@pytest.mark.parametrize("success", [False, True])
def test_initial_terminal_evaluator_blocks_first_action(create_toolkit, success):
    api = create_toolkit(env=FakeEnv(end_after=0, success=success))
    assert api.planner_stop_result is not None
    assert api.execute_tool("move_eef", {"poses": [POSE]}).is_error
    assert not api.env.chunk_calls


def test_tactile_baseline_reports_measured_change_and_invalid_markers():
    frame = observation(255)
    frame["step"] = 3
    result = tactile_statistics(frame)
    left = result["fingers"]["left"]
    assert left["mean_rgb_change"] == 1.0
    assert left["changed_pixel_fraction"] == 1.0
    assert left["reference_kind"] == "episode_initial_contact"
    assert left["valid_markers"] == 1 and left["marker_count"] == 2
    assert left["median_marker_displacement_magnitude"] == 5.0
    assert "success" not in result and "force" not in left
    frame["tactile"]["left"]["reference_rgb"] = np.zeros((2, 2, 3))
    with pytest.raises(ValueError, match="shape mismatch"):
        tactile_statistics(frame)
