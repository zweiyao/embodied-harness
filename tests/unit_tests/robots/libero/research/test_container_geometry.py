# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Geometry evidence must not turn sparse surface samples into success claims."""

import runpy
from pathlib import Path

import numpy as np
import pytest

RUN = runpy.run_path(
    str(
        Path(__file__).resolve().parents[5]
        / "examples/manual-workbench/sensor_container_geometry.py"
    )
)["run"]
RIM = [[80, 128], [128, 80], [176, 128], [128, 176]]


def frame():
    row, col = np.mgrid[:256, :256]
    world = np.stack(
        [(col - 128) / 1000, (row - 128) / 1000, np.full_like(row, 0.13, dtype=float)],
        axis=-1,
    )
    return {
        "step": 7,
        "proprio": {"robot0_eef_pos": [0.01, 0.02, 0.25]},
        "cameras": {
            "agentview": {
                "world": world + 10,
                "high": {"world": world, "rgb": np.zeros((256, 256, 3))},
            }
        },
    }


def test_center_and_point_relation_use_observed_world_geometry():
    f = frame()
    f["cameras"]["agentview"]["high"]["world"][126:131, 126:131, 2] = 0.09
    result = RUN(
        [f],
        {
            "rim_points": RIM,
            "image_size": [256, 256],
            "object_bottom_point": [128, 128],
        },
    )
    assert result["status"] == "measured"
    assert result["opening"]["center_xy"] == pytest.approx([0, 0])
    assert result["eef_to_opening_xy"] == pytest.approx([-0.01, -0.02])
    assert result["relation"]["sample_inside_rim_polygon"] is True
    assert result["relation"]["sample_above_rim_m"] == pytest.approx(-0.04)
    assert "success" not in result
    mismatch = RUN([f], {"rim_points": [[4 * r + 1, 4 * c + 1] for r, c in RIM]})
    assert "error" in mismatch
    assert "opening" not in mismatch


def test_invalid_depth_withheld_and_background_neighbors_excluded():
    f = frame()
    world = f["cameras"]["agentview"]["high"]["world"]
    world[79:82, 127:130] = np.nan
    assert (
        RUN([f], {"rim_points": RIM, "image_size": [256, 256]})["status"]
        == "resample_flagged_points"
    )
    world[79:82, 127:130] = [0, 0, 0.13]
    world[79, 127:130] = [0, 0, 1]
    result = RUN([f], {"rim_points": RIM, "image_size": [256, 256]})
    assert result["status"] == "measured"
    assert result["rim_samples"][0]["excluded_neighbor_count"] == 3
    assert result["rim_samples"][0]["world_xyz"][2] == pytest.approx(0.13)
    world[79:82, 127:130] = [0, 0, 1]
    world[80, 128] = [0, 0, 0.13]
    assert "opening" not in RUN([f], {"rim_points": RIM, "image_size": [256, 256]})


def test_outside_point_and_unavailable_frame_are_not_success():
    result = RUN(
        [frame()],
        {
            "rim_points": RIM,
            "image_size": [256, 256],
            "object_bottom_point": [200, 200],
        },
    )
    assert result["relation"]["sample_inside_rim_polygon"] is False
    assert result["relation"]["sample_edge_margin_m"] < 0
    assert "error" in RUN([frame()], {"rim_points": RIM, "step": 0})
    result = RUN(
        [frame()], {"rim_points": [[256, 1], *RIM[1:]], "image_size": [256, 256]}
    )
    assert result["status"] == "resample_flagged_points"


def test_points_on_one_edge_do_not_define_opening():
    result = RUN(
        [frame()],
        {
            "rim_points": [[100, 80], [100, 100], [100, 120], [100, 140]],
            "image_size": [256, 256],
        },
    )
    assert result["status"] == "insufficient_opening_coverage"


def test_height_outlier_excluded_only_with_four_point_supermajority():
    f = frame()
    f["cameras"]["agentview"]["high"]["world"][199:202, 199:202, 2] = 0.0
    result = RUN([f], {"rim_points": [*RIM, [200, 200]], "image_size": [256, 256]})
    assert result["status"] == "measured"
    assert result["excluded_rim_indices"] == [4]
    assert result["opening"]["center_xy"] == pytest.approx([0, 0])
    result = RUN([f], {"rim_points": [*RIM[:3], [200, 200]], "image_size": [256, 256]})
    assert result["status"] == "inconsistent_rim"


def test_missing_high_resolution_does_not_fall_back_to_low_world():
    f = frame()
    del f["cameras"]["agentview"]["high"]
    result = RUN([f], {"rim_points": RIM, "image_size": [256, 256]})
    assert "high-resolution" in result["error"]
    assert "opening" not in result


def test_real_1024_pixels_keep_high_resolution_surface_and_rc_order():
    row, col = np.mgrid[:1024, :1024]
    world = np.stack(
        [(col - 512) / 1000, (row - 512) / 1000, np.full_like(row, 0.13, dtype=float)],
        axis=-1,
    ).astype(np.float16)
    f = frame()
    f["cameras"]["agentview"]["high"] = {
        "world": world,
        "rgb": np.zeros((1024, 1024, 3), dtype=np.uint8),
    }
    points = [[400, 500], [500, 400], [600, 500], [500, 600]]
    result = RUN([f], {"rim_points": points})
    assert result["status"] == "measured"
    assert result["depth_image_size"] == [1024, 1024]
    assert result["rim_samples"][0]["world_xyz"] == pytest.approx(
        world[400, 500].astype(float).tolist(), abs=1e-4
    )
