# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Replay a perception program on exported UniVTAC sensors, never a simulator."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from jsonschema import Draft202012Validator
from PIL import Image

from robots.libero.research.library import Sandbox, digest, validate_tools
from robots.univtac.pilot.evidence import FRAME


def load_frames(sensors_zip: str | Path, *, step: int | None = None) -> list[dict]:
    """Decode the selected step and up to three predecessors from the allowlist.

    ZIP entries are read by exact name, never extracted. Unknown frame fields
    and unrelated archive entries are never followed or decoded.
    """
    with ZipFile(sensors_zip) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Duplicate sensor archive entries")
        manifest = json.loads(archive.read("manifest.json"))
        steps = manifest.get("steps")
        if (
            manifest.get("schema_version") != 1
            or not isinstance(steps, list)
            or not steps
            or any(type(value) is not int or value < 0 for value in steps)
            or steps != list(range(len(steps)))
        ):
            raise ValueError("Expected a complete ordered sensor archive")
        if step is None:
            step = steps[-1]
        if type(step) is not int or step not in steps:
            raise ValueError("Unknown recorded step")

        def decode(value, schema, prefix, directory):
            result = {}
            for key, child_schema in schema.items():
                if key not in value:
                    continue
                child, field = value[key], f"{prefix}_{key}"
                if child_schema is not None:
                    result[key] = decode(child, child_schema, field, directory)
                elif isinstance(child, dict):
                    name = child.get("artifact")
                    if set(child) != {"artifact"} or name not in (
                        field + ".png",
                        field + ".npz",
                    ):
                        raise ValueError(f"Invalid sensor artifact reference: {field}")
                    raw = io.BytesIO(archive.read(f"{directory}/{name}"))
                    if name.endswith(".png"):
                        with Image.open(raw) as image:
                            result[key] = np.array(image)
                    else:
                        with np.load(raw, allow_pickle=False) as arrays:
                            if arrays.files != ["array"]:
                                raise ValueError("Expected one numeric sensor array")
                            result[key] = arrays["array"].copy()
                else:
                    result[key] = child
            return result

        frames = []
        for index in steps[max(0, step - 3) : step + 1]:
            directory = f"frames/{index:04d}"
            frame = json.loads(archive.read(f"{directory}/sensor_frame.json"))
            if frame.get("step") != index:
                raise ValueError("Sensor frame step differs from the manifest")
            frames.append(decode(frame, FRAME, "sensor", directory))
        return frames


def _sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def replay(tool, params, sensors_zip, *, step=None, image="embodied-sensor:pilot"):
    """Validate parameters and run candidate code only in the existing sandbox."""
    validate_tools([tool])
    Draft202012Validator(tool["parameters"]).validate(params)
    checksum = _sha256(sensors_zip)
    frames = load_frames(sensors_zip, step=step)
    if _sha256(sensors_zip) != checksum:
        raise ValueError("Sensor archive changed while loading")
    sandbox = Sandbox(image)
    result = sandbox.run(tool, params, frames)
    return {
        "validation": "replay_passed"
        if result.get("error") is None
        else "replay_failed",
        "scope": "Parameter and execution check; not task improvement evidence",
        "sensors": str(Path(sensors_zip).resolve()),
        "input_sha256": checksum,
        "steps": [frame["step"] for frame in frames],
        "tool_version": digest([tool]),
        "params": params,
        "sandbox_image": sandbox.image,
        "result": result,
    }


def main():
    """Save a new replay report; optionally publish only a passing candidate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensors", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--params", default="{}", help="JSON parameter object")
    parser.add_argument("--step", type=int)
    parser.add_argument("--image", default="embodied-sensor:pilot")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()
    if bool(args.library) != bool(args.metadata):
        parser.error("--library and --metadata must be supplied together")
    if args.output.exists():
        parser.error("Replay output already exists; use a new evidence path")
    metadata = json.loads(args.metadata.read_text()) if args.metadata else {}
    if args.library and not all(
        metadata.get(key) for key in ("source_run", "reason", "input_contract")
    ):
        parser.error("Publication requires source_run, reason and input_contract")
    tool = json.loads(args.candidate.read_text())
    report = replay(
        tool, json.loads(args.params), args.sensors, step=args.step, image=args.image
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    if report["validation"] != "replay_passed":
        raise SystemExit("Replay returned an error; report saved, tool not published")
    if args.library:
        from rpent.dashboard.workbench import publish, write_json

        metadata.update(
            validation="replay_passed", example=report["result"], replay=report
        )
        version = publish(args.library, tool, metadata)
        path = args.library / f"{version}.meta.json"
        write_json(path, {**json.loads(path.read_text()), **metadata})
    print(json.dumps({"report": str(args.output), "published": bool(args.library)}))


if __name__ == "__main__":
    main()
