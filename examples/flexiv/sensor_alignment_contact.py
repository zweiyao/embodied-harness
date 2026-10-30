# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Track a selected held feature against visible references and contact evidence."""

import numpy as np


def _vector(value, length):
    value = np.asarray(value, dtype=float)
    if value.shape != (length,) or not np.isfinite(value).all():
        raise ValueError(f"Expected {length} finite values")
    return value


def _pose(state):
    if (
        state.get("coordinate_frame") != "robot_base"
        or state.get("quaternion_order") != "wxyz"
    ):
        raise ValueError("State must use robot_base metres and wxyz quaternions")
    pose = _vector(state["tcp_pose"], 7)
    q = pose[3:]
    if abs(np.linalg.norm(q) - 1) > 0.001:
        raise ValueError("TCP quaternion must be unit length")
    w, x, y, z = q / np.linalg.norm(q)
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )
    return pose[:3], rotation


def _interval(before, after):
    actual = _pose(after["state"])[0] - _pose(before["state"])[0]
    result = {
        "steps": [before["step"], after["step"]],
        "actual_tcp_translation_mm": (actual * 1000).tolist(),
        "status": "insufficient_evidence",
        "undertravel_with_force_rise": None,
    }
    if after.get("previous_observation_step") != before["step"]:
        result["reason"] = (
            "Intermediate observations omitted; cannot attribute the window to one command."
        )
        return result
    command = after.get("command") or {}
    if command.get("action") != "move_eef_delta":
        result["reason"] = (
            "This observation does not follow a recorded EEF delta command."
        )
        return result
    delta = _vector(command["translation_m"], 3)
    length = np.linalg.norm(delta)
    if length < 1e-6:
        result["reason"] = "No commanded translation to compare."
        return result
    if np.linalg.norm(_vector(command["rotation_vector_rad"], 3)) > 1e-6:
        result["reason"] = (
            "Mixed rotation/translation: no translation-only contact flag."
        )
        return result
    direction = delta / length
    ratio = float(actual @ direction / length)
    result.update(
        requested_translation_mm=(delta * 1000).tolist(),
        travel_fraction=ratio,
        controller_reached=(after.get("action_result") or {}).get("reached"),
    )
    forces = [f["state"].get("ext_wrench_in_world") for f in (before, after)]
    if any(f is None for f in forces):
        result["reason"] = "Base-frame wrench missing; missing force is not zero force."
        return result
    first, last = [_vector(f, 6) for f in forces]
    opposing_change = float(-(last[:3] - first[:3]) @ direction)
    opposing_after = float(-last[:3] @ direction)
    result.update(
        status="measured",
        force_before_base_n=first[:3].tolist(),
        force_after_base_n=last[:3].tolist(),
        opposing_force_change_n=opposing_change,
        opposing_force_after_n=opposing_after,
        undertravel_with_force_rise=bool(
            ratio < 0.75 and opposing_change > 5.0 and opposing_after > 5.0
        ),
    )
    return result


def run(frames, params):
    """Compute evidence; this program neither commands motion nor scores success."""
    if not 1 <= len(frames) <= 4:
        raise ValueError("Supply one anchor and at most three comparison observations")
    steps = [f["step"] for f in frames]
    if steps != sorted(set(steps)) or steps[0] != params["anchor_step"]:
        raise ValueError(
            "Frames must start at anchor_step and have increasing unique IDs"
        )
    if steps[1:] != params["compare_steps"]:
        raise ValueError("Loaded frames do not match compare_steps")
    anchor = frames[0]
    localizations = {v["record_step"]: v for v in anchor.get("localizations", [])}
    ids = [params["feature_record"], *params["reference_records"]]
    if len(set(ids)) != len(ids) or not 2 <= len(ids) <= 3:
        raise ValueError("Choose one feature and one or two distinct reference records")
    selected = [localizations[i] for i in ids]
    if any(
        v["step"] != anchor["step"] or v["coordinate_frame"] != "robot_base"
        for v in selected
    ):
        raise ValueError(
            "All localizations must reference the same anchor observation in robot_base"
        )
    feature, *references = [_vector(v["point_base_m"], 3) for v in selected]
    reference = np.mean(references, axis=0)
    position, rotation = _pose(anchor["state"])
    feature_tcp = rotation.T @ (feature - position)
    samples, previous = [], None
    tracking = params.get("track_with_tcp", False)
    if type(tracking) is not bool:
        raise ValueError("track_with_tcp must be a boolean")
    anchor_width = anchor["state"].get("gripper_width_m")
    tracking_invalidated = False
    for frame in frames:
        position, rotation = _pose(frame["state"])
        sample = {"step": frame["step"]}
        width = frame["state"].get("gripper_width_m")
        tracking_invalidated |= frame.get("tracking_break_since_anchor", False)
        if frame is not anchor:
            if anchor_width is None or width is None:
                tracking_invalidated = True
            elif (
                not np.isfinite([anchor_width, width]).all()
                or abs(width - anchor_width) > 0.001
            ):
                tracking_invalidated = True
        if frame is not anchor and (not tracking or tracking_invalidated):
            sample.update(
                status="insufficient_evidence",
                reason="TCP tracking not assumed, or gripper opening changed/is unavailable; re-localize the held feature.",
            )
        else:
            point = feature if frame is anchor else position + rotation @ feature_tcp
            residual = (point - reference) * 1000
            sample.update(
                status="measured_anchor"
                if frame is anchor
                else "conditional_tcp_estimate",
                feature_minus_reference_mm=residual.tolist(),
                abs_residual_change_mm=(np.abs(residual) - np.abs(previous)).tolist()
                if previous is not None
                else None,
            )
            previous = residual
        samples.append(sample)
    return {
        "status": "evidence_computed",
        "coordinate_frame": "robot_base",
        "axis_order": ["x", "y", "z"],
        "reference_kind": "selected_visible_surface_centroid_not_hole_center",
        "reference_base_m": reference.tolist(),
        "selected_measurements": selected,
        "alignment": samples,
        "contact_intervals": [_interval(a, b) for a, b in zip(frames, frames[1:])],
        "contact_flag_thresholds": {
            "travel_fraction_below": 0.75,
            "opposing_force_rise_above_n": 5.0,
            "opposing_force_after_above_n": 5.0,
        },
        "assumptions": "TCP tracking requires a rigid, non-slipping grasp and stationary references. Constant gripper width does not verify no slip.",
        "interpretation": "Positive absolute residual change means farther from the selected reference on that axis. Undertravel plus opposing force rise suggests resistance, not its cause or a corrective direction.",
        "limits": "Reference selection and calibration errors are not bounded. No hole-center, insertion-depth, object-orientation alignment or task-success measurement. TCP arrival is not insertion. Force cannot determine a unique X/Y correction.",
    }
