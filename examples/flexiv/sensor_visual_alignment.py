# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Track selected visible centers/axes and report image-plane alignment changes."""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def _match(before, after, point):
    """Local normalized patch match; reject weak or repeated visual evidence."""
    x, y = np.rint(point).astype(int)
    radius, search = 7, 24
    h, w = before.shape
    if not radius <= x < w - radius or not radius <= y < h - radius:
        raise ValueError("Selected landmark is too close to the image boundary")
    patch = before[y - radius : y + radius + 1, x - radius : x + radius + 1]
    patch = patch - patch.mean()
    norm = np.linalg.norm(patch)
    if patch.std() < 5:
        return None, "low_texture"
    x0, x1 = max(radius, x - search), min(w - radius - 1, x + search)
    y0, y1 = max(radius, y - search), min(h - radius - 1, y + search)
    windows = sliding_window_view(
        after[y0 - radius : y1 + radius + 1, x0 - radius : x1 + radius + 1],
        patch.shape,
    )
    centered = windows - windows.mean(axis=(-2, -1), keepdims=True)
    scores = (centered * patch).sum(axis=(-2, -1)) / np.maximum(
        np.sqrt((centered**2).sum(axis=(-2, -1))) * norm, 1e-6
    )
    row, col = np.unravel_index(np.argmax(scores), scores.shape)
    best = float(scores[row, col])
    separated = scores.copy()
    separated[max(0, row - 3) : row + 4, max(0, col - 3) : col + 4] = -1
    if best < 0.85:
        return None, "weak_match"
    if best - separated.max() < 0.025:
        return None, "ambiguous_match"
    found = np.array([x0 + col, y0 + row], dtype=float)
    if np.max(np.abs(found - [x, y])) >= search:
        return None, "search_boundary"
    return found, best


def _measure(points):
    feature, reference = points[:2], points[2:]
    a, b = feature[1] - feature[0], reference[1] - reference[0]
    if min(np.linalg.norm(a), np.linalg.norm(b)) < 8:
        raise ValueError("Use center-to-axis-point distances of at least 8 pixels")
    axis = b / np.linalg.norm(b)
    error = feature[0] - reference[0]
    angle = (
        np.degrees(np.arctan2(a[1], a[0]) - np.arctan2(b[1], b[0])) + 90
    ) % 180 - 90
    return {
        "feature_minus_reference_px": np.round(error, 3).tolist(),
        "offset_along_reference_axis_px": round(float(error @ axis), 3),
        "offset_across_reference_axis_px": round(float(error @ [-axis[1], axis[0]]), 3),
        "axis_angle_error_deg": round(float(angle), 3),
        "center_distance_px": round(float(np.linalg.norm(error)), 3),
    }


def run(frames, params):
    """Use recorded RGB only; no depth query, motion command or success judgment."""
    expected = [params["anchor_step"], *params["compare_steps"]]
    if not 1 <= len(frames) <= 4 or [f["step"] for f in frames] != expected:
        raise ValueError("Frame IDs must match anchor and comparison steps")
    if expected != sorted(set(expected)):
        raise ValueError("Choose increasing unique observation IDs")
    points = np.array(
        [*params["feature_axis_px"], *params["reference_axis_px"]], dtype=float
    )
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("Supply four finite [x,y] points")
    updates = params.get("reselected_axes", [])
    if len({v["step"] for v in updates}) != len(updates) or any(
        v["step"] not in expected[1:] for v in updates
    ):
        raise ValueError("Re-selected annotations need unique comparison steps")
    updates = {v["step"]: v for v in updates}
    previous_image, previous_measurement, previous_frame = None, None, None
    samples = []
    for frame in frames:
        rgb = np.asarray(frame["rgb"])
        if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
            raise ValueError("Expected original uint8 RGB image")
        if frame["camera"] != params["camera"]:
            raise ValueError("Camera mismatch")
        gray = rgb.astype(np.float32).mean(axis=2)
        h, w = gray.shape
        selected = updates.get(frame["step"])
        if selected is not None:
            points = np.array(
                [*selected["feature_axis_px"], *selected["reference_axis_px"]],
                dtype=float,
            )
            if points.shape != (4, 2) or not np.isfinite(points).all():
                raise ValueError("Invalid current-frame annotations")
        if (points < 0).any() or (points[:, 0] >= w).any() or (points[:, 1] >= h).any():
            raise ValueError("Points must be inside the original image resolution")
        sample = {"step": frame["step"], "image_size_wh": [w, h]}
        if previous_image is not None and gray.shape != previous_image.shape:
            raise ValueError("Resolution changed; select a new anchor")
        if previous_image is not None and selected is None:
            tracked, quality = [], []
            for point in points:
                found, score = _match(previous_image, gray, point)
                back, _ = (
                    _match(gray, previous_image, found)
                    if found is not None
                    else (None, None)
                )
                if back is None or np.linalg.norm(back - point) > 1.5:
                    sample.update(
                        status="unknown",
                        reason=score if found is None else "forward_backward_mismatch",
                    )
                    samples.append(sample)
                    return {
                        "status": "tracking_lost",
                        "camera": params["camera"],
                        "samples": samples,
                        "next_observation": "Re-select visible centers and axis points on a clear current frame.",
                    }
                tracked.append(found)
                quality.append(round(score, 3))
            points = np.array(tracked)
            sample["tracking_ncc"] = quality
        measured = _measure(points)
        sample.update(
            status="selected_anchor"
            if previous_image is None
            else "reselected_current"
            if selected is not None
            else "tracked",
            landmarks_px=points.tolist(),
            **measured,
        )
        if previous_measurement is not None:
            sample["change"] = {
                "center_distance_px": round(
                    measured["center_distance_px"]
                    - previous_measurement["center_distance_px"],
                    3,
                ),
                "absolute_angle_deg": round(
                    abs(measured["axis_angle_error_deg"])
                    - abs(previous_measurement["axis_angle_error_deg"]),
                    3,
                ),
            }
            if frame.get("previous_observation_step") == previous_frame["step"]:
                sample["actual_tcp_delta_mm"] = np.round(
                    (
                        np.array(frame["state"]["tcp_pose"][:3])
                        - np.array(previous_frame["state"]["tcp_pose"][:3])
                    )
                    * 1000,
                    3,
                ).tolist()
                sample["command"] = frame.get("command", {})
        samples.append(sample)
        previous_image, previous_measurement, previous_frame = gray, measured, frame
    return {
        "status": "evidence_computed",
        "camera": params["camera"],
        "samples": samples,
        "units": "original image pixels; x right, y down; angle clockwise modulo 180 degrees",
        "interpretation": "Negative change means smaller projected center distance/absolute angle. Selected center identity is supplied by the caller, not detected by this program.",
        "limits": "2D evidence only: perspective, occlusion and grasp slip can change projection. Pixel offsets are not robot-base millimetres. No motion target, insertion clearance or success verdict. Large changes require a new anchor.",
    }
