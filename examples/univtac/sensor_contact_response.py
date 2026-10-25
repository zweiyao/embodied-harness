# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Measure recent hand motion and bilateral tactile response, without task truth."""

import numpy as np


def _markers(sensor):
    reference = np.asarray(sensor.get("marker_reference", []), dtype=float)
    displacement = np.asarray(sensor.get("marker_displacement", []), dtype=float)
    if reference.ndim != 2 or reference.shape[-1] != 2:
        return None
    if reference.shape != displacement.shape:
        return None
    valid = np.isfinite(reference).all(axis=1) & np.isfinite(displacement).all(axis=1)
    return reference[valid], displacement[valid]


def _finger(before, after, radius, minimum):
    result = {"status": "insufficient_markers", "matched_reference_positions": 0}
    first, last = _markers(before), _markers(after)
    if first is None or last is None or not len(first[0]) or not len(last[0]):
        return result
    # Native marker rows are resampled/shuffled each observation, not stable IDs.
    distance = np.linalg.norm(first[0][:, None] - last[0][None], axis=-1)
    target = distance.argmin(axis=1)
    source = np.arange(len(first[0]))
    valid = (distance[source, target] <= radius) & (
        distance.argmin(axis=0)[target] == source
    )
    result["matched_reference_positions"] = int(valid.sum())
    result["reference_match_fraction"] = float(
        valid.sum() / min(len(first[0]), len(last[0]))
    )
    if valid.sum() < minimum:
        return result
    delta = last[1][target[valid]] - first[1][source[valid]]
    result.update(
        status="measured",
        median_delta_xy_px=np.median(delta, axis=0).tolist(),
        median_change_px=float(np.median(np.linalg.norm(delta, axis=1))),
        p90_change_px=float(np.percentile(np.linalg.norm(delta, axis=1), 90)),
    )
    old, new = before.get("rgb"), after.get("rgb")
    if old is not None and new is not None:
        old, new = np.asarray(old, dtype=float), np.asarray(new, dtype=float)
        if old.shape == new.shape and np.isfinite(old).all() and np.isfinite(new).all():
            result["mean_rgb_change_0_1"] = float(np.abs(new - old).mean() / 255)
    return result


def run(frames, params):
    """Return temporal evidence from at most four ordered, recorded sensor frames."""
    if not 1 <= len(frames) <= 4:
        raise ValueError("Supply one to four recorded frames")
    radius = float(params.get("marker_match_radius_px", 1.0))
    minimum = params.get("min_marker_matches", 8)
    threshold = float(params.get("marker_change_threshold_px", 3.0))
    if not 0 < radius <= 8 or type(minimum) is not int or not 4 <= minimum <= 64:
        raise ValueError("Invalid reference-position matching parameters")
    if not 0 < threshold <= 100:
        raise ValueError("Invalid marker-change threshold")
    steps = [frame["step"] for frame in frames]
    if any(b <= a for a, b in zip(steps, steps[1:])):
        raise ValueError("Frames must have increasing step numbers")
    poses = np.asarray([f["state"]["eef_pose_wxyz"] for f in frames], dtype=float)
    if poses.shape != (len(frames), 7) or not np.isfinite(poses).all():
        raise ValueError("Expected finite measured hand poses [x,y,z,qw,qx,qy,qz]")
    qnorm = np.linalg.norm(poses[:, 3:], axis=1)
    if np.any(qnorm < 1e-8):
        raise ValueError("Invalid measured hand quaternion")
    quaternions = poses[:, 3:] / qnorm[:, None]
    intervals = []
    for index, (before, after) in enumerate(zip(frames, frames[1:])):
        translation = poses[index + 1, :3] - poses[index, :3]
        rotation = 2 * np.arccos(
            np.clip(abs(np.dot(quaternions[index], quaternions[index + 1])), 0, 1)
        )
        fingers = {
            side: _finger(
                before.get("tactile", {}).get(side, {}),
                after.get("tactile", {}).get(side, {}),
                radius,
                minimum,
            )
            for side in ("left", "right")
        }
        paired = all(f["status"] == "measured" for f in fingers.values())
        interval = {
            "steps": [before["step"], after["step"]],
            "hand_translation_world_m": translation.tolist(),
            "hand_translation_m": float(np.linalg.norm(translation)),
            "hand_rotation_rad": float(rotation),
            "fingers": fingers,
            "bilateral_marker_change": paired
            and all(f["median_change_px"] >= threshold for f in fingers.values()),
        }
        if paired:
            interval["left_minus_right_image_delta_xy_px"] = (
                np.asarray(fingers["left"]["median_delta_xy_px"])
                - fingers["right"]["median_delta_xy_px"]
            ).tolist()
        intervals.append(interval)
    repeated = False
    for before, after in zip(intervals, intervals[1:]):
        lengths = before["hand_translation_m"], after["hand_translation_m"]
        if min(lengths) < 0.0005:
            continue
        cosine = np.dot(
            before["hand_translation_world_m"], after["hand_translation_world_m"]
        ) / (lengths[0] * lengths[1])
        repeated |= bool(
            cosine > 0.95
            and before["bilateral_marker_change"]
            and after["bilateral_marker_change"]
        )
    references = {
        side: frames[-1]
        .get("tactile", {})
        .get(side, {})
        .get("reference_kind", "missing")
        for side in ("left", "right")
    }
    sufficient = bool(intervals) and all(
        finger["status"] == "measured"
        for interval in intervals
        for finger in interval["fingers"].values()
    )
    return {
        "steps": steps,
        "status": "measured" if sufficient else "insufficient_evidence",
        "thresholds": {
            "marker_match_radius_px": radius,
            "min_marker_matches": minimum,
            "marker_change_threshold_px": threshold,
        },
        "reference_kind": references,
        "reference_may_already_be_loaded": True
        if any(v == "episode_initial_contact" for v in references.values())
        else None,
        "intervals": intervals,
        "repeated_translation_with_bilateral_marker_change": repeated,
        "object_motion_measured": False,
        "additional_object_observation_needed_for_progress": True,
        "interpretation": (
            "Repeated hand motion accompanies bilateral tactile deformation; hand travel alone does not establish object progress."
            if repeated
            else "These measurements describe hand motion and tactile response; they do not establish object progress."
        ),
        "limits": "Marker deltas use each finger's image axes, not world force axes. No force, hole-axis, blockage, slip or task-success estimate is made.",
    }
