# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Replay one standard perception candidate on saved Flexiv observations only."""

import argparse
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator

from robots.libero.research.library import Sandbox, digest, validate_tools
from rpent.dashboard.workbench import publish


def candidate() -> dict:
    root = Path(__file__).parent
    definition = json.loads((root / "alignment_contact_metadata.json").read_text())
    definition["source"] = (root / "sensor_alignment_contact.py").read_text()
    validate_tools([definition])
    return definition


def recorded_frames(root: Path, params: dict) -> list[dict]:
    """Allowlist sensor records, preserving true observation/action adjacency."""
    Draft202012Validator(candidate()["parameters"]).validate(params)
    records = json.loads((root / "states.json").read_text())["steps"]
    by_step = {r["step_idx"]: r for r in records}
    observations = [
        r["step_idx"] for r in records if "perception.json" in r["artifacts"]
    ]
    selected = [params["anchor_step"], *params["compare_steps"]]
    if selected != sorted(set(selected)):
        raise ValueError("Choose an anchor followed by increasing observation steps")
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
        data = json.loads((root / "localization.json" / f"{step}.json").read_text())
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--params", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--image", default="embodied-sensor:pilot")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new report path; historical evidence is not overwritten")
    params = json.loads(args.params.read_text())
    definition = candidate()
    frames = recorded_frames(args.run, params)
    sandbox = Sandbox(args.image)
    result = sandbox.run(definition, params, frames)
    if result.get("error") or result.get("status") != "evidence_computed":
        raise ValueError("Replay did not produce a successful measurement result")
    report = {
        "source_run": str(args.run),
        "version": digest([definition]),
        "sandbox_image": sandbox.image,
        "params": params,
        "steps": [f["step"] for f in frames],
        "result": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    if args.library:
        publish(
            args.library,
            definition,
            {
                "source_run": str(args.run),
                "reason": "Repeated USB correction changed X while Y stayed near the selected reference; TCP reached did not establish insertion.",
                "input_contract": "Up to four recorded Flexiv observations, robot_base metres/wxyz, actual TCP and base wrench (N/Nm), plus source-matched native RGB-D surface localizations. No hardware access, raw truth or task evaluator.",
                "validation": "replay_passed",
                "example": result,
                "replay": {k: v for k, v in report.items() if k != "result"},
                "dependencies": ["localize_target"],
                "runtime_status": "candidate_only_not_wired_into_flexiv",
            },
        )
    print(
        json.dumps(
            {
                "version": report["version"],
                "report": str(args.output),
                "selected": False,
            }
        )
    )


if __name__ == "__main__":
    main()
