# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Measure a visible local surface from UniVTAC's optical-Z depth."""

import numpy as np


def run(frames, params):
    """Fit one selected surface; report world geometry and observable fit quality."""
    if not frames:
        return {"status": "unknown", "reason": "no recorded frame"}
    step = params.get("step", -1)
    frame = (
        frames[-1]
        if step == -1
        else next((f for f in frames if f["step"] == step), None)
    )
    if frame is None:
        return {"status": "unknown", "reason": "step outside latest four frames"}
    camera = params["camera"]
    result = {
        "status": "unknown",
        "step": frame["step"],
        "camera": camera,
        "coordinate_frame": "world",
        "units": "m",
    }

    def unknown(reason):
        return {**result, "reason": reason}

    sensor = frame.get("cameras", {}).get(camera, {})
    calibration = sensor.get("calibration", {})
    if "depth" not in sensor or not all(
        k in calibration
        for k in ("intrinsics", "position_w", "quaternion_wxyz", "height", "width")
    ):
        return unknown("missing depth or calibration")
    if (
        calibration.get("camera_convention") != "ros_optical"
        or sensor.get("depth_units", calibration.get("depth_units")) != "m"
    ):
        return unknown("requires native UniVTAC optical-Z depth in metres")
    depth = np.asarray(sensor["depth"]).squeeze()
    if depth.shape != (calibration["height"], calibration["width"]):
        return unknown("depth and calibration resolution differ")
    r0, c0, r1, c1 = params["region_rc"]
    if not (0 <= r0 < r1 <= depth.shape[0] and 0 <= c0 < c1 <= depth.shape[1]):
        return unknown("region outside native image")
    if min(r1 - r0, c1 - c0) < 4 or (r1 - r0) * (c1 - c0) > 4096:
        return unknown(
            "select a 2D surface patch, at least 4x4 and at most 4096 pixels"
        )
    k = np.asarray(calibration["intrinsics"], dtype=float)
    q = np.asarray(calibration["quaternion_wxyz"], dtype=float)
    origin = np.asarray(calibration["position_w"], dtype=float)
    if (
        k.shape != (3, 3)
        or q.shape != (4,)
        or origin.shape != (3,)
        or not all(np.isfinite(a).all() for a in (k, q, origin))
        or abs(np.linalg.det(k)) < 1e-9
        or abs(np.linalg.norm(q) - 1) > 1e-3
    ):
        return unknown("invalid camera calibration")
    rows, cols = np.mgrid[r0:r1, c0:c1]
    z = depth[r0:r1, c0:c1]
    valid = np.isfinite(z) & (z > 0)
    result.update(region_rc=[r0, c0, r1, c1], points=int(valid.sum()))
    if valid.sum() < 16 or valid.mean() < 0.8:
        return unknown("insufficient valid depth coverage")
    rays = (
        np.stack([cols[valid], rows[valid], np.ones(valid.sum())], axis=1)
        @ np.linalg.inv(k).T
    )
    points = rays * (z[valid] / rays[:, 2])[:, None]
    center = points.mean(axis=0)
    _, singular, vh = np.linalg.svd(points - center, full_matrices=False)
    normal = vh[-1]
    if normal @ center > 0:
        normal = -normal  # Choose the camera-facing sign; not an insertion direction.
    residual = np.abs((points - center) @ normal)
    rms = float(np.sqrt(np.mean(residual**2)))
    ratio = float(singular[-1] / max(singular[-2], 1e-12))
    result.update(
        rms_m=round(rms, 6),
        p95_residual_m=round(float(np.quantile(residual, 0.95)), 6),
        normal_to_tangent_ratio=round(ratio, 5),
    )
    if singular[-2] < 1e-5 or ratio > 0.1 or rms > 0.002:
        return unknown(
            "patch is narrow, curved or contains multiple surfaces; choose one visible flat patch"
        )
    # A low global residual alone can hide curvature or a foreground/background boundary.
    angles = []
    for top in (True, False):
        for left in (True, False):
            mask = ((rows[valid] < (r0 + r1) / 2) == top) & (
                (cols[valid] < (c0 + c1) / 2) == left
            )
            part = points[mask]
            if len(part) < 4:
                continue
            _, values, basis = np.linalg.svd(
                part - part.mean(axis=0), full_matrices=False
            )
            if values[1] > 1e-5:
                angles.append(
                    float(np.degrees(np.arccos(np.clip(abs(basis[-1] @ normal), 0, 1))))
                )
    spread = max(angles) if angles else None
    result["quadrant_normal_spread_deg"] = (
        round(spread, 2) if spread is not None else None
    )
    if len(angles) < 3 or spread > 10:
        return unknown("local surface directions disagree or have insufficient support")
    w, x, y, z = q / np.linalg.norm(q)
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    result.update(
        status="measured",
        center_world_m=np.round(rotation @ center + origin, 6).tolist(),
        normal_world=np.round(rotation @ normal, 6).tolist(),
        limitation="Visible patch only. Normal points toward camera; it is not necessarily an object/hole axis or evidence of insertion.",
    )
    return result
