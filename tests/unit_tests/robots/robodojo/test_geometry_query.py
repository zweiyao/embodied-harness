# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Check opt-in measurement modes without accessing the simulator."""

from types import SimpleNamespace

import numpy as np
import pytest

from robots.robodojo.geometry import fit_circle, optional_geometry_tools, query_geometry


def test_fit_circle_and_reject_uninformative_points():
    angles = np.arange(8) * np.pi / 4
    points = np.column_stack(
        (0.2 + 0.03 * np.cos(angles), 0.03 * np.sin(angles), np.ones(8))
    )
    result = fit_circle(points)
    assert result["center_world_xyz"] == pytest.approx([0.2, 0, 1])
    assert result["radius_m"] == pytest.approx(0.03)
    assert result["normal_world_xyz"] == pytest.approx([0, 0, 1])
    assert "unavailable" in fit_circle(points[:3])
    assert "unavailable" in fit_circle(np.column_stack([np.arange(6)] * 3))


def test_modes_share_samples_and_reject_stale_observations(monkeypatch):
    camera = {
        "distance_to_image_plane": np.ones((3, 3)),
        "intrinsic_matrix": np.eye(3),
        "extrinsic_matrix": np.eye(4),
    }
    camera["distance_to_image_plane"][0, 0] = np.nan
    sensor = SimpleNamespace(_last_obs={"vision": {"cam_head": camera}})
    state = SimpleNamespace(latest_record=lambda: SimpleNamespace(step_idx=4))
    monkeypatch.delenv("RPENT_ROBODOJO_GEOMETRY", raising=False)
    assert not optional_geometry_tools()
    measurements = {}
    for mode in ("raw", "fit"):
        monkeypatch.setenv("RPENT_ROBODOJO_GEOMETRY", mode)
        assert optional_geometry_tools() == [query_geometry]
        with pytest.raises(ValueError, match="Stale"):
            query_geometry(sensor, state, 3, "cam_head", [(0, 1)])
        measurements[mode] = query_geometry(
            sensor, state, 4, "cam_head", [(0, 0), (0, 1)]
        ).data
    assert measurements["raw"]["samples"] == measurements["fit"]["samples"]
    assert measurements["raw"]["valid_fraction"] == 0.5
    assert "circle" not in measurements["raw"]
    assert "unavailable" in measurements["fit"]["circle"]


def test_json_pixel_pairs_pass_toolkit_strict_validation():
    args = {"observation_step": 0, "camera": "cam_head", "pixels": [[11, 20], [12, 19]]}
    validated = query_geometry.args_schema.model_validate(args, strict=True)
    assert validated.pixels == args["pixels"]
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        query_geometry.args_schema.model_validate(
            {**args, "pixels": [[11]]}, strict=True
        )
