# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Replay one standard perception candidate on saved Flexiv observations only."""

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from robots.flexiv.sensors import alignment_frames
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

    def load(name, step):
        directory = root / name
        padded = directory / f"{step:02d}.json"
        path = padded if padded.exists() else directory / f"{step}.json"
        return json.loads(path.read_text())

    return alignment_frames(records, load, params)


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
                "input_adapter": "flexiv.alignment.v1",
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
