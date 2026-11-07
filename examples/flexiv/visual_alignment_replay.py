# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Replay image alignment in the existing sensor sandbox, never on hardware."""

import argparse
import json
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator
from PIL import Image

from robots.flexiv.sensors import visual_alignment_frames
from robots.libero.research.library import Sandbox, digest, validate_tools
from rpent.dashboard.workbench import publish


def candidate():
    root = Path(__file__).parent
    tool = json.loads((root / "visual_alignment_metadata.json").read_text())
    tool["source"] = (root / "sensor_visual_alignment.py").read_text()
    validate_tools([tool])
    return tool


def recorded_frames(root, params):
    Draft202012Validator(candidate()["parameters"]).validate(params)
    records = json.loads((root / "states.json").read_text())["steps"]

    def load(name, step):
        path = root / name / f"{step:02d}.png"
        if not path.exists():
            path = root / name / f"{step}.png"
        with Image.open(path) as picture:
            return np.array(picture.convert("RGB"))

    return visual_alignment_frames(records, load, params)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--params", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--library", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh report path")
    tool = candidate()
    params = json.loads(args.params.read_text())
    result = Sandbox("embodied-sensor:pilot").run(
        tool, params, recorded_frames(args.run, params)
    )
    if result.get("error"):
        raise ValueError(result["error"])
    report = {
        "source_run": str(args.run),
        "version": digest([tool]),
        "params": params,
        "result": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.library:
        if result.get("status") != "evidence_computed":
            raise ValueError("Do not publish from a tracking-lost replay")
        publish(
            args.library,
            tool,
            {
                "source_run": str(args.run),
                "validation": "replay_passed",
                "reason": "Measure visible axis mismatch and projected offset changes after a local correction. Selected centers remain caller annotations; not automatic object recognition.",
                "input_adapter": "flexiv.visual_alignment.v1",
                "dependencies": [],
                "input_contract": "1–4 numbered side OR wrist RGB observations at original resolution; uint8 RGB, image x right/y down. Only measured TCP/action metadata. No hidden geometry. Caller supplies visible center/axis points; uncertain tracking returns unknown.",
                "example": result,
                "replay": {
                    "manual_reselection_count": len(params.get("reselected_axes", [])),
                    "effectiveness": "Not tested in a new robot episode or model A/B trial",
                },
            },
        )
    print(
        json.dumps(
            {
                "version": report["version"],
                "status": result.get("status"),
                "selected": False,
            }
        )
    )


if __name__ == "__main__":
    main()
