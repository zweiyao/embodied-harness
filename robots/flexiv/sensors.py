# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read-only observation bundles for isolated Flexiv perception programs."""

import math
from collections.abc import Callable


def alignment_frames(
    records: list[dict], load: Callable[[str, int], dict], params: dict
) -> list[dict]:
    """Select at most four observations and source-matched localization results.

    Only measured state, requested actions and localization evidence are exposed.
    ``load`` reads an artifact by name and step from the existing record store.
    """
    by_step = {r["step_idx"]: r for r in records}
    observations = [
        r["step_idx"] for r in records if "perception.json" in r["artifacts"]
    ]
    selected = [params["anchor_step"], *params["compare_steps"]]
    if not 1 <= len(selected) <= 4 or selected != sorted(set(selected)):
        raise ValueError(
            "Choose an anchor followed by increasing observation steps (at most four)"
        )
    if any(step not in observations for step in selected):
        raise ValueError(
            "Selected step is not a sensor observation; localization/query IDs are not observation IDs"
        )
    localization_ids = [params["feature_record"], *params["reference_records"]]
    if len(set(localization_ids)) != len(localization_ids):
        raise ValueError("Choose distinct feature and reference records")
    measurements = []
    for step in localization_ids:
        if step not in by_step:
            raise ValueError(f"Unknown localization record {step}")
        record = by_step[step]
        if "localization.json" not in record["artifacts"]:
            raise ValueError(f"Record {step} is not a localization result")
        data = load("localization.json", step)
        if (
            data["step"] != selected[0]
            or record["command"].get("source_step") != selected[0]
        ):
            raise ValueError("All selected measurements must come from anchor_step")
        measurements.append(
            {
                "record_step": step,
                **{
                    k: data[k]
                    for k in (
                        "step",
                        "camera",
                        "pixel",
                        "box",
                        "target",
                        "coordinate_frame",
                        "point_base_m",
                        "depth_m",
                        "depth_patch_spread_m",
                        "valid_patch_pixels",
                        "source",
                        "captured_at",
                        "calibration_validation",
                    )
                },
            }
        )
    frames = []
    anchor_width = by_step[selected[0]]["state"].get("gripper_width_m")
    for step in selected:
        record = by_step[step]
        state = record["state"]
        previous_index = observations.index(step) - 1
        previous_step = observations[previous_index] if previous_index >= 0 else None
        if previous_step is not None and any(
            previous_step < r["step_idx"] < step
            and (r.get("command") or {}).get("action")
            for r in records
        ):
            previous_step = None
        tracking_break = False
        for prior in records:
            if not selected[0] < prior["step_idx"] <= step:
                continue
            if (prior.get("command") or {}).get("action") == "set_gripper":
                tracking_break = True
            if "perception.json" in prior["artifacts"]:
                width = prior["state"].get("gripper_width_m")
                if (
                    anchor_width is None
                    or width is None
                    or not math.isfinite(anchor_width)
                    or not math.isfinite(width)
                    or abs(width - anchor_width) > 0.001
                ):
                    tracking_break = True
        frames.append(
            {
                "step": step,
                "previous_observation_step": previous_step,
                "tracking_break_since_anchor": tracking_break,
                "state": {
                    k: state[k]
                    for k in (
                        "tcp_pose",
                        "coordinate_frame",
                        "quaternion_order",
                        "gripper_width_m",
                        "ext_wrench_in_world",
                    )
                    if k in state
                },
                "command": {
                    k: v
                    for k, v in (record.get("command") or {}).items()
                    if k in ("action", "translation_m", "rotation_vector_rad")
                },
                "action_result": {
                    k: v
                    for k, v in (record.get("result") or {}).items()
                    if k in ("reached", "position_error_m")
                },
                "localizations": measurements if step == selected[0] else [],
            }
        )
    return frames
