# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Historical replay must preserve segmentation with both metadata names."""

import numpy as np
import pytest

from robots.libero.research.manual_library import recorded_frames
from rpent.session import EnvState


@pytest.mark.parametrize(
    "metadata_name",
    ["segment_00_mask_alignment.json", "mask_alignment_segment_00.json"],
)
def test_replay_loads_same_camera_mask(tmp_path, metadata_name):
    state = EnvState(tmp_path)
    with state.record_step(
        state={
            "robot0_eef_pos": [0, 0, 0],
            "robot0_eef_quat": [0, 0, 0, 1],
            "robot0_gripper_qpos": [0.04, -0.04],
        },
        terminated=False,
    ) as step:
        for camera in ("agentview", "wrist"):
            state.save(f"{camera}.png", np.zeros((4, 4, 3), dtype=np.uint8), step=step)
            state.save(f"{camera}_depth.npz", np.ones((4, 4)), step=step)
            state.save(f"{camera}_world.npz", np.ones((4, 4, 3)), step=step)
            state.save(f"{camera}_metadata.json", {}, step=step)
        mask = np.zeros((8, 8), dtype=bool)
        mask[2:6, 2:6] = True
        state.save("segment_00_mask.npz", mask, step=step)
        state.save(
            metadata_name,
            {
                "camera": "agentview",
                "mask_artifact": "segment_00_mask.npz",
                "source_artifact": "agentview_high.png",
                "source_shape": [8, 8],
            },
            step=step,
        )
    frames = recorded_frames(tmp_path, step=0)
    item = frames[0]["masks"]["segment_00_mask.npz"]
    assert item["camera"] == "agentview"
    assert item["mask"].shape == (4, 4)
    assert item["mask"][1, 1] and not item["mask"][0, 0]
