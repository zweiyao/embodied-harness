# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Verify image tracking and failure semantics inside the sensor sandbox."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from examples.flexiv.visual_alignment_replay import candidate
from robots.libero.research.library import Sandbox, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output path")
    rng = np.random.default_rng(7)
    first = np.zeros((128, 160, 3), dtype=np.uint8)
    first[30:90, 10:50] = rng.integers(0, 256, (60, 40, 3), dtype=np.uint8)
    first[30:90, 70:110] = rng.integers(0, 256, (60, 40, 3), dtype=np.uint8)
    last = first.copy()
    last[30:90, 10:54] = 0
    last[30:90, 14:54] = first[30:90, 10:50]
    params = {
        "anchor_step": 0,
        "compare_steps": [1],
        "camera": "wrist",
        "feature_axis_px": [[30, 50], [30, 75]],
        "reference_axis_px": [[90, 50], [90, 75]],
    }
    frames = [
        {
            "step": i,
            "camera": "wrist",
            "rgb": rgb,
            "previous_observation_step": i - 1,
            "state": {"tcp_pose": [0.004 * i, 0, 0, 1, 0, 0, 0]},
            "command": {"action": "move_eef_delta", "translation_m": [0.004, 0, 0]},
        }
        for i, rgb in enumerate([first, last])
    ]
    tool, sandbox = candidate(), Sandbox("embodied-sensor:pilot")
    result = sandbox.run(tool, params, frames)
    sample = result["samples"][-1]
    checks = {
        "tracked_known_shift": sample["status"] == "tracked"
        and sample["change"]["center_distance_px"] == -4,
        "preserve_robot_displacement_units": sample["actual_tcp_delta_mm"] == [4, 0, 0],
        "no_fabricated_angle": sample["axis_angle_error_deg"] == 0,
    }
    missing = copy.deepcopy(frames)
    missing[1]["rgb"][:] = 0
    loss = sandbox.run(tool, params, missing)
    checks["occlusion_returns_unknown"] = (
        loss["status"] == "tracking_lost" and "change" not in loss["samples"][-1]
    )
    annotated = {
        **params,
        "reselected_axes": [
            {
                "step": 1,
                "feature_axis_px": [[34, 50], [59, 50]],
                "reference_axis_px": [[90, 50], [90, 75]],
            }
        ],
    }
    updated = sandbox.run(tool, annotated, frames)["samples"][-1]
    checks["reselection_is_labeled_and_angle_measured"] = (
        updated["status"] == "reselected_current"
        and updated["axis_angle_error_deg"] == -90
    )
    skipped = copy.deepcopy(frames)
    skipped[1]["previous_observation_step"] = None
    checks["skipped_actions_not_attributed"] = (
        "actual_tcp_delta_mm" not in sandbox.run(tool, params, skipped)["samples"][-1]
    )
    bad = {**params, "feature_axis_px": [[-1, 20], [30, 30]]}
    try:
        sandbox.run(tool, bad, frames)
    except RuntimeError as exc:
        checks["out_of_frame_rejected"] = "inside the original image" in str(exc)
    else:
        checks["out_of_frame_rejected"] = False
    report = {
        "version": digest([tool]),
        "checks": checks,
        "known_shift_result": result,
        "limitations": "Synthetic tracking and geometry checks; not robot effectiveness or autonomous landmark selection.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(checks))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
