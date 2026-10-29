# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Fixed sensor statistics; these are baselines, not learned contact diagnoses."""

import numpy as np


def tactile_statistics(frame: dict) -> dict:
    """Measure image/reference differences and available marker displacement.

    Image change is not contact area. An initial reference can already contain
    contact, and pixel displacement is not calibrated physical force.
    """
    result = {
        "step": frame["step"],
        "units": "pixels; RGB difference normalized to 0..1",
        "fingers": {},
    }
    for finger, sensor in frame.get("tactile", {}).items():
        measured = {"reference_kind": sensor.get("reference_kind", "not_recorded")}
        rgb, reference = sensor.get("rgb"), sensor.get("reference_rgb")
        if rgb is not None and reference is not None:
            rgb, reference = np.asarray(rgb), np.asarray(reference)
            if rgb.shape != reference.shape or rgb.ndim != 3 or rgb.shape[-1] != 3:
                raise ValueError(f"{finger}: reference/image shape mismatch")
            delta = (
                np.abs(rgb.astype(float) - reference.astype(float)).mean(axis=-1) / 255
            )
            changed = delta > 0.02
            locations = np.argwhere(changed)
            measured.update(
                mean_rgb_change=float(delta.mean()),
                changed_pixel_fraction=float(changed.mean()),
                change_threshold=0.02,
                change_centroid_rc=locations.mean(axis=0).tolist()
                if len(locations)
                else None,
                image_size=list(rgb.shape[:2]),
            )
        else:
            measured["image_change"] = "reference_not_recorded"
        displacement = sensor.get("marker_displacement")
        if displacement is not None:
            displacement = np.asarray(displacement, dtype=float)
            if displacement.ndim != 2 or displacement.shape[-1] != 2:
                raise ValueError(f"{finger}: expected marker displacement [N,2]")
            valid = np.isfinite(displacement).all(axis=1)
            values = displacement[valid]
            lengths = np.linalg.norm(values, axis=1)
            measured.update(
                marker_count=int(len(displacement)),
                valid_markers=int(valid.sum()),
                mean_marker_displacement_xy=values.mean(axis=0).tolist()
                if len(values)
                else None,
                median_marker_displacement_magnitude=float(np.median(lengths))
                if len(values)
                else None,
                p95_marker_displacement_magnitude=float(np.percentile(lengths, 95))
                if len(values)
                else None,
            )
        else:
            measured["marker_displacement"] = "not_recorded"
        measured["tracking_quality"] = sensor.get("tracking_quality", "not_recorded")
        result["fingers"][finger] = measured
    return result
