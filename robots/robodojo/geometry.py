# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Estimate a circle from measured surface points in one coordinate frame."""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt

from rpent.tools import ToolResult, tool


def fit_circle(world_xyz: list[list[float]]) -> dict:
    """Fit a plane then a circle; reject clustered, partial or inconsistent rims."""
    import numpy as np

    points = np.unique(np.asarray(world_xyz, dtype=float), axis=0)
    if len(points) < 5:
        return {"unavailable": "need at least five distinct valid points"}
    if not np.isfinite(points).all():
        return {"unavailable": "nonfinite world coordinates"}
    origin = points.mean(axis=0)
    offsets = points - origin
    _, singular, axes = np.linalg.svd(offsets, full_matrices=False)
    if singular[1] <= 0.05 * singular[0]:
        return {"unavailable": "nearly collinear samples"}
    uv = offsets @ axes[:2].T
    system = np.column_stack([2 * uv, np.ones(len(uv))])
    params = np.linalg.lstsq(system, (uv**2).sum(axis=1), rcond=None)[0]
    relative = uv - params[:2]
    distances = np.linalg.norm(relative, axis=1)
    radius = distances.mean()
    angles = np.sort(np.arctan2(relative[:, 1], relative[:, 0]))
    if np.diff(angles, append=angles[0] + 2 * np.pi).max() > np.pi:
        return {"unavailable": "samples do not cover opposing sides of the rim"}
    height = offsets @ axes[2]
    rms = np.sqrt(np.mean(height**2 + (distances - radius) ** 2))
    if rms > 0.20 * radius:
        return {"unavailable": "large residual relative to radius", "rms_m": float(rms)}
    normal = axes[2]
    # A plane has no intrinsic positive side. Use a deterministic sign.
    normal = normal * np.sign(normal[np.argmax(np.abs(normal))])
    return {
        "center_world_xyz": (origin + params[:2] @ axes[:2]).tolist(),
        "normal_world_xyz": normal.tolist(),
        "radius_m": float(radius),
        "rms_m": float(rms),
    }


@tool(readonly=True, exclude=("primitives", "state"))
def query_geometry(
    primitives: Any,
    state: Any,
    observation_step: StrictInt,
    camera: Literal["cam_head", "cam_left_wrist", "cam_right_wrist"],
    pixels: Annotated[
        list[tuple[StrictInt, StrictInt]], Field(min_length=1, max_length=32)
    ],
) -> ToolResult:
    """Measure selected (row, col) pixels on the latest image in world metres.

    For circular geometry, select points spread around one visible rim. Each
    sample uses the same depth and calibration as back_project. The fit-enabled
    configuration also reports the fitted circle or why it is unavailable.
    """
    from robots.robodojo.tools import back_project

    mode = os.environ.get("RPENT_ROBODOJO_GEOMETRY")
    if mode not in ("raw", "fit"):
        raise ValueError("Geometry query is disabled")
    if observation_step != state.latest_record().step_idx:
        raise ValueError("Stale observation_step; use the latest observation")
    if primitives._last_obs is None:
        raise ValueError("No cached observation")
    samples = []
    for row, col in pixels:
        sample = back_project(primitives, state, row, col, camera).to_dict()
        samples.append({**sample, "pixel": [row, col], "valid": "world_xyz" in sample})
    xyz = [sample["world_xyz"] for sample in samples if sample["valid"]]
    result = {
        "observation_step": observation_step,
        "camera": camera,
        "samples": samples,
        "valid_fraction": len(xyz) / len(samples),
    }
    if mode == "fit":
        result["circle"] = fit_circle(xyz)
    return ToolResult(data=result)


def optional_geometry_tools():
    return (
        [query_geometry]
        if os.environ.get("RPENT_ROBODOJO_GEOMETRY") in ("raw", "fit")
        else []
    )
