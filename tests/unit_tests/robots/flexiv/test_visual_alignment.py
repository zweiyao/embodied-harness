# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Check visual-tool input isolation and compact-feedback preservation."""

import copy

import numpy as np
import pytest

from examples.flexiv.visual_alignment_replay import candidate
from robots.flexiv.catalog import generated_availability
from robots.flexiv.feedback import compact_camera_metadata
from robots.flexiv.sensors import visual_alignment_frames


def test_visual_adapter_selects_only_requested_camera_and_measured_state():
    records = [
        {
            "step_idx": i,
            "artifacts": ["perception.json", "wrist.png", "side.png"],
            "state": {"tcp_pose": [0, 0, 0, 1, 0, 0, 0], "hidden_pose": 999},
            "command": {
                "action": "move_eef_delta",
                "translation_m": [0.004, 0, 0],
                "truth": 99,
            },
        }
        for i in (24, 25)
    ]
    reads = []

    def load(name, step):
        reads.append((name, step))
        return np.zeros((720, 1280, 3), dtype=np.uint8)

    params = {"anchor_step": 24, "compare_steps": [25], "camera": "wrist"}
    frames = visual_alignment_frames(records, load, params)
    assert reads == [("wrist.png", 24), ("wrist.png", 25)]
    assert frames[1]["previous_observation_step"] == 24
    assert set(frames[0]["state"]) == {"tcp_pose"}
    assert "truth" not in frames[1]["command"]
    with pytest.raises(ValueError, match="observation"):
        visual_alignment_frames(records, load, {**params, "compare_steps": [26]})
    with pytest.raises(ValueError, match="increasing"):
        visual_alignment_frames(records, load, {**params, "compare_steps": [24]})


def test_visual_catalog_contract_preserves_old_adapter_and_rejects_missing_inputs():
    tool = {**candidate(), "input_adapter": "flexiv.visual_alignment.v1"}
    assert generated_availability(tool) == (True, None)
    tool["parameters"]["required"].remove("camera")
    assert not generated_availability(tool)[0]


def test_compact_metadata_keeps_geometry_quality_and_does_not_mutate_records():
    original = {
        "T_base_board": [[1]],
        "calibration_validation": {"wrist_passed": False},
        "cameras": {
            "wrist": {
                "image_size": [1280, 720],
                "sequence": 2,
                "frame_age_s": 0.02,
                "depth_scale_m": 0.001,
                "color_depth_skew_s": 0.004,
                "producer_pid": 42,
                "host_received_s": 123,
                "serial": "device",
            }
        },
    }
    saved = copy.deepcopy(original)
    result = compact_camera_metadata(original)
    assert original == saved
    assert result["T_base_board"] == original["T_base_board"]
    assert result["calibration_validation"] == original["calibration_validation"]
    assert result["cameras"]["wrist"] == {
        k: v
        for k, v in saved["cameras"]["wrist"].items()
        if k not in ("producer_pid", "host_received_s", "serial")
    }
