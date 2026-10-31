# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Exercise candidate arithmetic in Docker; no hardware or model requests."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from examples.flexiv.alignment_contact_replay import candidate
from robots.libero.research.library import Sandbox, digest


def frame(step, xyz=(0, 0, 0), previous=None, force=0.0):
    return {
        "step": step,
        "previous_observation_step": previous,
        "state": {
            "tcp_pose": [*xyz, 1, 0, 0, 0],
            "coordinate_frame": "robot_base",
            "quaternion_order": "wxyz",
            "gripper_width_m": 0.004,
            "ext_wrench_in_world": [0, 0, force, 0, 0, 0],
        },
        "command": {
            "action": "move_eef_delta",
            "translation_m": [0, 0, -0.002],
            "rotation_vector_rad": [0, 0, 0],
        },
        "action_result": {"reached": True},
        "localizations": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="embodied-sensor:pilot")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh report path")
    tool, sandbox = candidate(), Sandbox(args.image)
    first = frame(0)
    first["localizations"] = [
        {
            "record_step": i,
            "step": 0,
            "point_base_m": point,
            "coordinate_frame": "robot_base",
        }
        for i, point in [(1, [0.01, 0, 0]), (2, [0, -0.01, 0]), (3, [0, 0.01, 0])]
    ]
    params = {
        "anchor_step": 0,
        "feature_record": 1,
        "reference_records": [2, 3],
        "compare_steps": [4, 5],
        "track_with_tcp": True,
    }
    frames = [
        first,
        frame(4, [-0.008, 0.001, 0], 0, 2),
        frame(5, [-0.016, 0.001, -0.001], 4, 14),
    ]
    output = sandbox.run(tool, params, frames)
    checks = {}
    checks["xyz_residual_sign_units_and_worsening"] = bool(
        np.allclose(output["alignment"][1]["feature_minus_reference_mm"], [2, 1, 0])
        and np.allclose(
            output["alignment"][2]["feature_minus_reference_mm"], [-6, 1, -1]
        )
        and np.allclose(output["alignment"][2]["abs_residual_change_mm"], [4, 0, 1])
    )
    interval = output["contact_intervals"][-1]
    checks["arrival_true_does_not_hide_undertravel_force_rise"] = (
        interval["controller_reached"] is True
        and interval["travel_fraction"] == 0.5
        and interval["opposing_force_change_n"] == 12
        and interval["undertravel_with_force_rise"] is True
    )
    copied = copy.deepcopy(frames)
    copied[1]["state"]["ext_wrench_in_world"][2] = 14
    copied[-1]["state"]["ext_wrench_in_world"][2] = -0.4
    copied[-1]["state"]["tcp_pose"][2] = 0.001
    copied[-1]["command"]["translation_m"] = [0, 0, 0.003]
    result = sandbox.run(tool, params, copied)
    checks["retracting_and_unloading_is_not_opposing_force_buildup"] = (
        result["contact_intervals"][-1]["undertravel_with_force_rise"] is False
    )
    turned = frame(4)
    turned["state"]["tcp_pose"][3:] = [np.sqrt(0.5), 0, 0, np.sqrt(0.5)]
    result = sandbox.run(tool, {**params, "compare_steps": [4]}, [first, turned])
    checks["wxyz_rotation_moves_offset_feature"] = bool(
        np.allclose(
            result["alignment"][1]["feature_minus_reference_mm"], [0, 10, 0], atol=1e-9
        )
    )
    copied = copy.deepcopy(frames)
    copied[-1]["previous_observation_step"] = 99
    result = sandbox.run(tool, params, copied)
    checks["skipped_observations_do_not_attribute_last_command"] = (
        result["contact_intervals"][-1]["undertravel_with_force_rise"] is None
    )
    copied = copy.deepcopy(frames)
    copied[-1]["state"].pop("ext_wrench_in_world")
    result = sandbox.run(tool, params, copied)
    checks["missing_force_is_unknown_not_zero"] = (
        result["contact_intervals"][-1]["undertravel_with_force_rise"] is None
    )
    copied = copy.deepcopy(frames)
    copied[1]["state"]["gripper_width_m"] = 0.02
    result = sandbox.run(tool, params, copied)
    checks["opening_then_reclosing_invalidates_old_anchor"] = all(
        "feature_minus_reference_mm" not in row for row in result["alignment"][1:]
    )
    copied = copy.deepcopy(frames)
    copied[-1]["tracking_break_since_anchor"] = True
    result = sandbox.run(tool, params, copied)
    checks["intermediate_release_invalidates_unselected_frames"] = (
        "feature_minus_reference_mm" not in result["alignment"][-1]
    )
    result = sandbox.run(tool, {**params, "track_with_tcp": False}, frames)
    checks["no_rigid_assumption_no_propagation"] = all(
        "feature_minus_reference_mm" not in row for row in result["alignment"][1:]
    )
    copied = copy.deepcopy(frames)
    copied[-1]["command"]["rotation_vector_rad"] = [0.1, 0, 0]
    result = sandbox.run(tool, params, copied)
    checks["mixed_rotation_has_no_translation_only_contact_flag"] = (
        result["contact_intervals"][-1]["undertravel_with_force_rise"] is None
    )
    copied = copy.deepcopy(frames)
    copied[0]["localizations"][0]["step"] = 3
    try:
        sandbox.run(tool, params, copied)
    except RuntimeError as error:
        checks["mismatched_source_observation_rejected"] = (
            "same anchor observation" in str(error)
        )
    else:
        checks["mismatched_source_observation_rejected"] = False
    report = {
        "version": digest([tool]),
        "sandbox_image": sandbox.image,
        "checks": checks,
        "passed": all(checks.values()),
        "scope": "Synthetic arithmetic and evidence handling; not robot-task improvement",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
