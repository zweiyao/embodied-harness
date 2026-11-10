# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Visible-region projection and single-use alignment contracts."""

import copy
import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from scipy.spatial.transform import Rotation

from robots.libero.research.placement import PlacementTools, placement_geometry
from rpent.tools import ToolResult


def observation(angle=0, translation=(0, 0, 0)):
    """Known plane seen by a translated, yaw-rotated camera."""
    h, w = 161, 201
    k = np.array([[200, 0, 100], [0, 200, 80], [0, 0, 1.0]])
    c2w = np.eye(4)
    c2w[:3, :3] = Rotation.from_euler("z", angle).as_matrix()
    c2w[:3, 3] = translation
    rows, cols = np.indices((h, w))
    camera_points = np.stack(
        [(cols - 100) / 200, (rows - 80) / 200, np.ones((h, w))], axis=-1
    )
    world = camera_points @ c2w[:3, :3].T + c2w[:3, 3]
    high = {
        "rgb": np.zeros((h, w, 3), dtype=np.uint8),
        "world": world,
        "calibration": {
            "height": h,
            "width": w,
            "intrinsic_K": k,
            "extrinsic_cam2world": c2w,
        },
    }
    pose = {
        "robot0_eef_pos": np.array([0.1, 0.1, 1.2]) + translation,
        "robot0_eef_quat": np.array([0, 0, 0, 1.0]),
        "robot0_gripper_qpos": np.array([0.02, -0.02]),
    }
    frame = {
        "step": 3,
        "proprio": pose,
        "cameras": {"agentview": {"high": high}, "wrist": {"high": high}},
    }
    params = {
        "step": 3,
        "camera": "agentview",
        "held_feature": [80, 80],
        "target_region": [[60, 80], [60, 120], [100, 120], [100, 80]],
        "plane_samples": [[40, 60], [40, 140], [120, 140], [120, 60]],
    }
    return frame, params


def instance(frame):
    calls = []
    raw = copy.deepcopy(frame["proprio"])

    def move(xyz, **kwargs):
        calls.append({"xyz": xyz, **kwargs})
        return ToolResult(data={"steps_used": 1})

    p = SimpleNamespace(
        env=SimpleNamespace(terminated=False, truncated=False, raw_obs=lambda: raw),
        move_to=move,
    )
    return PlacementTools(SimpleNamespace(frames=lambda: [frame]), p), calls, raw


@pytest.mark.parametrize(
    "angle,translation", [(0, (0, 0, 0)), (0.7, (0.4, -0.2, 0.15))]
)
def test_intersection_uses_plane_and_preserves_held_offset_not_cavity_depth(
    angle, translation
):
    frame, params = observation(angle, translation)
    high = frame["cameras"]["agentview"]["high"]
    eef = frame["proprio"]["robot0_eef_pos"]
    values = {k: params[k] for k in ("held_feature", "target_region", "plane_samples")}
    result = placement_geometry(high, eef, **values)
    center = np.array(translation) + [0, 0, 1]
    np.testing.assert_allclose(result["selected_region_center_xyz"], center, atol=1e-12)
    expected = eef.copy()
    expected[:2] += center[:2] - np.array(result["held_feature_xyz"])[:2]
    np.testing.assert_allclose(result["eef_target_xyz_keep_height"], expected)
    # Only the surface behind the selected region changes; plane anchors/object do not.
    for r, c in params["target_region"]:
        high["world"][r - 1 : r + 2, c - 1 : c + 2] = [17, -12, 9]
    changed = placement_geometry(high, eef, **values)
    np.testing.assert_allclose(
        changed["selected_region_center_xyz"], center, atol=1e-12
    )
    assert result["semantic_status"] == "caller_selected_not_verified"


@pytest.mark.parametrize(
    "replacement",
    [
        [[20, 30], [30, 40], [40, 50], [50, 60]],
        [[20, 30], [20, 70], [60, 30], [60, 70]],
        [[20, 30], [20, 70], [30, 50], [60, 30]],
    ],
)
def test_degenerate_crossed_or_nonconvex_region_has_no_preview(replacement):
    frame, params = observation()
    tools, calls, _ = instance(frame)
    params["target_region"] = replacement
    result = tools.preview_placement(**params)
    assert result.data["status"] == "resample_required"
    assert "preview_id" not in result.data
    assert len(result.images) == 2
    assert not calls


@pytest.mark.parametrize(
    "kind",
    [
        "nonfinite",
        "rigid",
        "dimensions",
        "singular",
        "no_high",
        "steep",
        "collinear",
        "inconsistent",
    ],
)
def test_invalid_geometry_never_produces_an_executable_target(kind):
    frame, params = observation()
    high = frame["cameras"]["agentview"]["high"]
    if kind == "nonfinite":
        high["calibration"]["intrinsic_K"][0, 0] = np.nan
    if kind == "rigid":
        high["calibration"]["extrinsic_cam2world"][0, 0] = 2
    if kind == "dimensions":
        high["calibration"]["width"] += 1
    if kind == "singular":
        high["calibration"]["intrinsic_K"][0] = 0
    if kind == "no_high":
        frame["cameras"]["agentview"] = {}
    if kind == "steep":
        high["world"][..., 2] += high["world"][..., 0]
    if kind == "collinear":
        params["plane_samples"] = [[20, 30], [30, 40], [40, 50], [50, 60]]
    if kind == "inconsistent":
        high["world"][39:42, 59:62, 2] += 0.08
    tools, calls, _ = instance(frame)
    result = tools.preview_placement(**params)
    assert "preview_id" not in result.data
    assert not calls


@pytest.mark.parametrize(
    "point", [[0.5, 0.5], ["20", 30], ["\t", 20, 30], [-1, 30], [True, 30]]
)
def test_pixel_contract_rejects_other_units_or_malformed_pairs(point):
    frame, params = observation()
    tools, _, _ = instance(frame)
    params["held_feature"] = point
    with pytest.raises(ValueError):
        tools.preview_placement.args_schema.model_validate(params)


def test_out_of_image_pixel_and_large_correction_return_no_id():
    frame, params = observation()
    tools, calls, _ = instance(frame)
    result = tools.preview_placement(**{**params, "held_feature": [161, 30]})
    assert result.data["status"] == "resample_required"
    result = tools.preview_placement(**{**params, "held_feature": [80, 10]})
    assert result.data["status"] == "requires_waypoint"
    assert "preview_id" not in result.data
    assert not calls


def test_preview_images_and_one_commit_keep_target_without_retyping_or_gripper():
    frame, params = observation()
    tools, calls, raw = instance(frame)
    result = tools.preview_placement(**params)
    assert result.data["status"] == "review_required"
    assert len(result.images) == 2
    assert Image.open(io.BytesIO(result.images[0])).size == (201, 161)
    assert result.data["crop_coordinate_rule"].startswith("Inputs remain integer")
    # An unchanged-frame observation does not expire the preview.
    tools.sensors.frames()
    aligned = tools.align_placement(result.data["preview_id"])
    assert not aligned.is_error
    assert calls == [{"xyz": result.data["eef_target_xyz_keep_height"], "gripper": 0.0}]
    assert tools.align_placement(result.data["preview_id"]).is_error
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change", ["step", "pose", "calibration", "replaced", "failed", "id", "terminated"]
)
def test_stale_or_changed_preview_never_moves(change):
    frame, params = observation()
    tools, calls, raw = instance(frame)
    result = tools.preview_placement(**params)
    preview_id = result.data["preview_id"]
    if change == "step":
        frame["step"] += 1
    if change == "pose":
        raw["robot0_eef_pos"][0] += 0.01
    if change == "calibration":
        frame["cameras"]["agentview"]["high"]["calibration"]["intrinsic_K"][0, 0] += 1
    if change == "replaced":
        tools.preview_placement(**params)
    if change == "failed":
        tools.preview_placement(**{**params, "step": 0})
    if change == "id":
        preview_id = "invented"
    if change == "terminated":
        tools.primitives.env.terminated = True
    assert tools.align_placement(preview_id).is_error
    assert not calls
