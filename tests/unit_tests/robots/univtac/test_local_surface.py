# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Known geometry and ambiguity checks for the directly authored tool."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from examples.univtac.tools.local_surface import run
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
