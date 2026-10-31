# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Small-displacement image evidence from two recorded left tactile frames."""

import numpy as np


def compare(before, after, metadata_before, metadata_after):
    """Track local image features with forward/backward consistency filtering."""
    import cv2

    for metadata in (metadata_before, metadata_after):
        if metadata.get("status") != "available":
            raise ValueError("Both steps require available, fresh tactile recordings")
    for key in ("serial", "side", "capture_session", "resolution_wh"):
        if metadata_before[key] != metadata_after[key]:
            raise ValueError(f"Tactile frames differ in {key}")
    if metadata_after["sequence"] <= metadata_before["sequence"]:
        raise ValueError("Choose two different tactile frames in chronological order")
    if before.shape != after.shape or before.ndim != 3:
        raise ValueError("Tactile images must have matching RGB shapes")
    if list(before.shape[1::-1]) != metadata_before["resolution_wh"]:
        raise ValueError("Recorded resolution does not match tactile image")
    scale = min(1.0, 640 / before.shape[1])
    images = [
        cv2.cvtColor(cv2.resize(image, None, fx=scale, fy=scale), cv2.COLOR_RGB2GRAY)
        for image in (before, after)
    ]
    mask = np.zeros_like(images[0])
    h, w = mask.shape
    mask[h // 10 : -h // 10, w // 10 : -w // 10] = 255
    points = cv2.goodFeaturesToTrack(images[0], 250, 0.03, 12, mask=mask, blockSize=7)
    result = {
        "units": "original image pixels",
        "axes": "x right, y down; not robot base axes",
        "analysis_resolution_wh": [w, h],
        "elapsed_s": metadata_after["received_at_s"] - metadata_before["received_at_s"],
        "reference_load": "unknown; before frame is not an unloaded calibration",
        "interpretation": (
            "Relative surface image motion only. Combine with commanded/actual TCP "
            "and RGB views. This does not establish slip, force or insertion success. "
            "Repeated dot patterns can alias large motion; only local tracking is supported."
        ),
        "status": "insufficient_evidence",
        "detected_features": 0 if points is None else len(points),
        "valid_features": 0,
    }
    if points is None:
        return result
    options = {"winSize": (15, 15), "maxLevel": 0}
    forward, good, error = cv2.calcOpticalFlowPyrLK(*images, points, None, **options)
    if forward is None:
        return result
    backward, back_good, _ = cv2.calcOpticalFlowPyrLK(
        images[1], images[0], forward, None, **options
    )
    if backward is None:
        return result
    displacement = (forward - points).reshape(-1, 2)
    fb_error = np.linalg.norm((backward - points).reshape(-1, 2), axis=1)
    valid = (
        (good.ravel() == 1)
        & (back_good.ravel() == 1)
        & (error.ravel() < 20)
        & (fb_error < 0.5)
        & (np.linalg.norm(displacement, axis=1) < 5)
        & np.isfinite(displacement).all(axis=1)
    )
    count = int(valid.sum())
    result.update(valid_features=count, valid_fraction=count / len(points))
    if count < 12 or count / len(points) < 0.5:
        return result
    displacement = displacement[valid] / scale
    median = np.median(displacement, axis=0)
    result.update(
        status="measured",
        median_displacement_xy_px=median.tolist(),
        displacement_magnitude_p90_px=float(
            np.percentile(np.linalg.norm(displacement, axis=1), 90)
        ),
        residual_magnitude_p90_px=float(
            np.percentile(np.linalg.norm(displacement - median, axis=1), 90)
        ),
    )
    return result
