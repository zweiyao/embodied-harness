# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Run small synthetic behavioral checks inside the perception Docker sandbox."""

import argparse
import json
from pathlib import Path

import numpy as np

from robots.libero.research.library import Sandbox, digest, validate_tools


def frame(step, *, permutation=None, shift=(0.0, 0.0), reference_shift=0.0):
    reference = np.array([[x, y] for x in range(4) for y in range(4)], dtype=float) * 20
    displacement = reference * [0.1, -0.2] + np.asarray(shift)
    if permutation is not None:
        reference, displacement = reference[permutation], displacement[permutation]
    return {
        "step": step,
        "state": {"eef_pose_wxyz": [0, 0, 0, 1, 0, 0, 0]},
        "tactile": {
            side: {
                "marker_reference": reference + reference_shift,
                "marker_displacement": displacement,
                "reference_kind": "episode_initial_contact",
            }
            for side in ("left", "right")
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="embodied-sensor:pilot")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new report path; existing evidence is not overwritten")
    root = Path(__file__).parent
    tool = json.loads((root / "contact_response_metadata.json").read_text())
    tool["source"] = (root / "sensor_contact_response.py").read_text()
    validate_tools([tool])
    sandbox = Sandbox(args.image)
    checks = {}

    value = sandbox.run(
        tool, {}, [frame(0), frame(1, permutation=np.arange(15, -1, -1))]
    )
    fingers = value["intervals"][0]["fingers"]
    checks["row_permutation_creates_no_change"] = value["status"] == "measured" and all(
        f["matched_reference_positions"] == 16 and f["median_change_px"] == 0
        for f in fingers.values()
    )

    value = sandbox.run(tool, {}, [frame(0), frame(1, reference_shift=1000)])
    fingers = value["intervals"][0]["fingers"]
    checks["unmatched_markers_are_insufficient_not_zero"] = (
        value["status"] == "insufficient_evidence"
        and all(f["matched_reference_positions"] == 0 for f in fingers.values())
        and all("median_change_px" not in f for f in fingers.values())
    )

    repeated_rows = np.tile(np.array([0, 1]), 32)
    value = sandbox.run(
        tool,
        {},
        [frame(0, permutation=repeated_rows), frame(1, permutation=repeated_rows)],
    )
    checks["padding_does_not_inflate_effective_matches"] = value[
        "status"
    ] == "insufficient_evidence" and all(
        f["matched_reference_positions"] == 2
        for f in value["intervals"][0]["fingers"].values()
    )

    moved = frame(1, shift=(3, 4))
    moved["state"]["eef_pose_wxyz"] = [
        0.003,
        0.004,
        0,
        np.cos(np.pi / 12),
        0,
        0,
        np.sin(np.pi / 12),
    ]
    value = sandbox.run(tool, {}, [frame(0), moved])
    interval = value["intervals"][0]
    checks["measured_motion_and_marker_delta_have_correct_units"] = bool(
        np.allclose(interval["hand_translation_world_m"], [0.003, 0.004, 0])
        and np.isclose(interval["hand_translation_m"], 0.005)
        and np.isclose(interval["hand_rotation_rad"], np.pi / 6)
        and all(
            np.allclose(f["median_delta_xy_px"], [3, 4])
            and np.isclose(f["median_change_px"], 5)
            for f in interval["fingers"].values()
        )
    )

    single = frame(0)
    single["tactile"] = {}
    value = sandbox.run(tool, {}, [single])
    checks["one_missing_tactile_frame_does_not_imply_unloaded_or_progress"] = (
        value["status"] == "insufficient_evidence"
        and value["intervals"] == []
        and value["reference_may_already_be_loaded"] is None
        and value["object_motion_measured"] is False
    )

    report = {
        "tool_version": digest([tool]),
        "sandbox_image": sandbox.image,
        "scope": "Synthetic measurement behavior; no model, simulator, or task-effect claim",
        "checks": checks,
        "passed": all(checks.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
