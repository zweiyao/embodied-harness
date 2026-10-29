# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Generated sensors receive the same recorded high-resolution surface map."""

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from robots.libero import tools
from robots.libero.research.manual_library import recorded_frames
from robots.libero.research.sensors import PROPRIO
from rpent.session import EnvState

EXAMPLES = Path(__file__).resolve().parents[5] / "examples/manual-workbench"
PATCH = runpy.run_path(str(EXAMPLES / "sensor_patch_batch.py"))["run"]


def save_frame(state, value, *, high=True, depth=False):
    with state.record_step(state=dict.fromkeys(PROPRIO, [0, 0, 0])) as step:
        for camera, offset in (("agentview", 0), ("wrist", 10)):
            v = value + offset
            state.save(f"{camera}.png", np.full((4, 4, 3), v, np.uint8), step=step)
            state.save(f"{camera}_depth.npz", np.full((4, 4), v), step=step)
            state.save(f"{camera}_world.npz", np.full((4, 4, 3), v), step=step)
            state.save(f"{camera}_metadata.json", {}, step=step)
            if high:
                state.save(
                    f"{camera}_high.png", np.full((16, 16, 3), v, np.uint8), step=step
                )
                state.save(
                    f"{camera}_world_high.npz",
                    np.full((16, 16, 3), v + 0.5, np.float16),
                    step=step,
                )
            if depth:
                state.save(
                    f"{camera}_depth_high.npz", np.full((16, 16), v + 0.25), step=step
                )
                state.save(
                    f"{camera}_metadata_high.json",
                    {
                        "camera_name": camera,
                        "height": 16,
                        "width": 16,
                        "hidden_object": "not a sensor",
                    },
                    step=step,
                )


def test_history_keeps_same_step_camera_and_original_low_data(tmp_path):
    state = EnvState(tmp_path)
    for value in range(1, 6):
        save_frame(state, value, depth=value == 5)
    frames = recorded_frames(tmp_path)
    assert [f["step"] for f in frames] == [1, 2, 3, 4]
    for f in frames:
        for camera, offset in (("agentview", 0), ("wrist", 10)):
            v = f["step"] + 1 + offset
            data = f["cameras"][camera]
            np.testing.assert_array_equal(data["world"], np.full((4, 4, 3), v))
            high = data["high"]
            assert high["step"] == f["step"] and high["camera"] == camera
            assert high["world"].dtype == np.float16
            np.testing.assert_array_equal(high["world"], np.full((16, 16, 3), v + 0.5))
            assert high["source_artifacts"]["world"] == f"{camera}_world_high.npz"
            assert high["image_size"] == [16, 16]
            if f["step"] == 4:
                assert high["depth"][0, 0] == v + 0.25
                assert "hidden_object" not in high["calibration"]
            else:
                assert "depth" not in high and "calibration" not in high


def test_old_frames_remain_loadable_without_fabricating_high_data(tmp_path):
    state = EnvState(tmp_path)
    save_frame(state, 1, high=False)
    f = recorded_frames(tmp_path)[0]
    assert "high" not in f["cameras"]["agentview"]
    assert "high-resolution" in PATCH([f], {"points": [[0.5, 0.5]]})["error"]


def test_patch_uses_real_high_map_and_missing_metric_depth_is_explicit(tmp_path):
    state = EnvState(tmp_path)
    save_frame(state, 1)
    f = recorded_frames(tmp_path)[0]
    high = f["cameras"]["agentview"]["high"]
    high["world"][8:11, 5:8] = [0.1, 0.2, 0.3]
    result = PATCH([f], {"points": [[9 / 15, 6 / 15]], "radius": 1})
    assert result["patches"][0]["pixel_rc"] == [9, 6]
    assert result["patches"][0]["world_median_xyz"] == pytest.approx(
        [0.1, 0.2, 0.3], abs=1e-4
    )
    assert result["depth_status"] == "not_recorded"
    assert result["patches"][0]["depth_p10_p90"] is None
    high["depth"] = np.full((16, 16), 0.8)
    result = PATCH([f], {"points": [[9 / 15, 6 / 15]], "radius": 1})
    assert result["depth_status"] == "recorded"
    assert result["patches"][0]["depth_p10_p90"] == [0.8, 0.8]
    high["depth"] = np.ones((4, 4))
    assert "mismatch" in PATCH([f], {"points": [[0.5, 0.5]]})["error"]


def test_dump_saves_actual_rendered_high_depth_and_calibration(tmp_path):
    state = EnvState(tmp_path)
    rendered = []

    def meta(camera_name, height, width):
        return {
            "camera_name": camera_name,
            "height": height,
            "width": width,
            "intrinsic_K": [[width, 0, width / 2], [0, height, height / 2], [0, 0, 1]],
            "extrinsic_cam2world": np.eye(4).tolist(),
        }

    def render(camera_name, height, width, depth):
        assert depth is True
        rendered.append((camera_name, height, width))
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        d = np.broadcast_to(
            np.arange(height, dtype=np.float32)[:, None] / height + 1, (height, width)
        ).copy()
        return rgb, d

    primitives = SimpleNamespace(
        env=SimpleNamespace(get_camera_meta=meta, render_camera=render),
        _last_obs={"main_images": np.zeros((256, 256, 3), dtype=np.uint8)},
    )
    raw = {
        name: np.ones(shape, dtype=dtype)
        for name, shape, dtype in [
            ("agentview_image", (256, 256, 3), np.uint8),
            ("agentview_depth", (256, 256), np.float32),
            ("robot0_eye_in_hand_image", (256, 256, 3), np.uint8),
            ("robot0_eye_in_hand_depth", (256, 256), np.float32),
        ]
    }
    with state.record_step(state=dict.fromkeys(PROPRIO, [0, 0, 0])) as step:
        tools._save_observation_artifacts(primitives, state, step, raw)
    assert rendered == [("agentview", 1024, 1024), ("robot0_eye_in_hand", 1024, 1024)]
    for camera in ("agentview", "wrist"):
        depth = state.load(f"{camera}_depth_high.npz", step=0)
        calibration = state.load(f"{camera}_metadata_high.json", step=0)
        world = state.load(f"{camera}_world_high.npz", step=0)
        assert depth.shape == (1024, 1024) and depth[0, 0] > depth[-1, 0]
        assert calibration["height"] == calibration["width"] == 1024
        np.testing.assert_array_equal(
            world, tools._world_from_depth(depth, calibration).astype(np.float16)
        )


@pytest.mark.parametrize(
    "candidate,source",
    [
        ("candidate.json", "sensor_patch_batch.py"),
        ("container_candidate.json", "sensor_container_geometry.py"),
    ],
)
def test_published_candidate_source_matches_reviewable_file(candidate, source):
    assert (
        json.loads((EXAMPLES / candidate).read_text())["source"]
        == (EXAMPLES / source).read_text()
    )
