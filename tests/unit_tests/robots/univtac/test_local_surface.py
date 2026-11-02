# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Known geometry and ambiguity checks for the directly authored tool."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from examples.univtac.tools.local_surface import _common_tangent
from examples.univtac.tools.local_surface import _surface as run
from examples.univtac.tools.local_surface import run as batch_run
from robots.libero.research.library import validate_tools

PARAMS = {"camera": "head", "region_rc": [0, 0, 24, 24]}


def frame():
    rows, cols = np.mgrid[:24, :24]
    # z + 0.5*x = 1, known normal up to sign.
    depth = 1 / (1 + 0.5 * (cols - 12) / 100)
    return {
        "step": 7,
        "cameras": {
            "head": {
                "depth": depth,
                "depth_units": "m",
                "calibration": {
                    "intrinsics": [[100, 0, 12], [0, 100, 12], [0, 0, 1]],
                    "height": 24,
                    "width": 24,
                    "quaternion_wxyz": [1, 0, 0, 0],
                    "position_w": [0, 0, 0],
                    "camera_convention": "ros_optical",
                },
            }
        },
    }


def test_known_tilt_and_world_rotation_and_translation():
    f = frame()
    expected = -np.array([0.5, 0, 1]) / np.sqrt(1.25)
    base = run([f], PARAMS)
    assert base["status"] == "measured"
    np.testing.assert_allclose(base["normal_world"], expected, atol=1e-6)
    assert base["rms_m"] == 0
    f["cameras"]["head"]["calibration"].update(
        quaternion_wxyz=[np.sqrt(0.5), 0, 0, np.sqrt(0.5)], position_w=[1, 2, 3]
    )
    result = run([f], PARAMS)
    np.testing.assert_allclose(
        result["normal_world"], [0, expected[0], expected[2]], atol=1e-6
    )
    x, y, z = base["center_world_m"]
    np.testing.assert_allclose(
        result["center_world_m"], [1 - y, 2 + x, 3 + z], atol=1e-6
    )
    assert len(json.dumps(result, allow_nan=False)) < 1500


@pytest.mark.parametrize(
    "case",
    [
        "holes",
        "two_surfaces",
        "curve",
        "resolution",
        "quaternion",
        "units",
        "outside",
        "thin",
        "missing",
        "old_frame",
    ],
)
def test_ambiguous_or_missing_data_does_not_return_direction(case):
    f, p = frame(), copy.deepcopy(PARAMS)
    s = f["cameras"]["head"]
    if case == "holes":
        s["depth"][:12] = np.nan
    elif case == "two_surfaces":
        s["depth"][:, 12:] += 0.1
    elif case == "curve":
        s["depth"] = (
            1 + ((np.arange(24)[None, :] - 12) / 100) ** 2 * 10 + np.zeros((24, 1))
        )
    elif case == "resolution":
        s["calibration"]["width"] = 32
    elif case == "quaternion":
        s["calibration"]["quaternion_wxyz"] = [0, 0, 0, 0]
    elif case == "units":
        s["depth_units"] = "mm"
    elif case == "outside":
        p["region_rc"] = [0, 0, 25, 24]
    elif case == "thin":
        p["region_rc"] = [0, 0, 2, 24]
    elif case == "missing":
        del s["calibration"]
    else:
        p["step"] = 0
    result = run([f], p)
    assert result["status"] == "unknown"
    assert "normal_world" not in result
    json.dumps(result, allow_nan=False)


def test_declared_source_and_frame_selection():
    root = Path("examples/univtac/tools/local_surface")
    tool = json.loads(root.with_suffix(".json").read_text())
    tool["source"] = root.with_suffix(".py").read_text()
    validate_tools([tool])
    assert len(tool["description"]) < 700
    f = frame()
    later = copy.deepcopy(f)
    later["step"] = 8
    later["cameras"]["head"]["depth"] *= 2
    selected = run([f, later], {**PARAMS, "step": 7})
    latest = run([f, later], PARAMS)
    np.testing.assert_allclose(
        np.array(selected["center_world_m"]) * 2, latest["center_world_m"], atol=2e-6
    )
    assert run([], PARAMS)["status"] == "unknown"


def test_common_tangent_of_known_cylinder_and_ambiguity():
    axis = np.array([0.3, -0.4, 0.8])
    axis /= np.linalg.norm(axis)
    first = np.cross(axis, [1.0, 0, 0])
    first /= np.linalg.norm(first)
    second = np.cross(axis, first)
    normals = [np.cos(a) * first + np.sin(a) * second for a in (0.1, 0.7, 1.3, 1.9)]
    result = _common_tangent(normals)
    assert result["axis_status"] == "measured"
    np.testing.assert_allclose(result["common_tangent_world"], axis, atol=1e-6)
    assert _common_tangent(normals[:2])["axis_status"] == "unknown"
    assert _common_tangent([first] * 3)["axis_status"] == "unknown"
    assert _common_tangent(np.eye(3))["axis_status"] == "unknown"


def test_batch_rejects_single_plane_as_unique_axis_and_is_compact():
    result = batch_run(
        [frame()],
        {
            "camera": "head",
            "regions_rc": [
                [0, 0, 12, 12],
                [0, 12, 12, 24],
                [12, 0, 24, 12],
                [12, 12, 24, 24],
            ],
        },
    )
    assert all(p["status"] == "measured" for p in result["patches"])
    assert result["axis_status"] == "unknown"
    assert "common_tangent_world" not in result
    assert len(json.dumps(result, allow_nan=False)) < 1500


def test_common_tangent_rejects_one_outlier_and_reports_support():
    axis = np.array([0.3, -0.4, 0.8])
    axis /= np.linalg.norm(axis)
    first = np.cross(axis, [1.0, 0, 0])
    first /= np.linalg.norm(first)
    second = np.cross(axis, first)
    normals = [np.cos(a) * first + np.sin(a) * second for a in (0.1, 0.7, 1.3)] + [axis]
    result = _common_tangent(normals)
    assert result["axis_status"] == "measured"
    assert result["normal_indices"] == [0, 1, 2]
    np.testing.assert_allclose(result["common_tangent_world"], axis, atol=1e-6)


def test_equal_support_for_distinct_directions_is_ambiguous():
    assert (
        _common_tangent([[1, 0, 0], [0, 1, 0], [1, 0, 0], [0, 0, 1]])["axis_status"]
        == "unknown"
    )
