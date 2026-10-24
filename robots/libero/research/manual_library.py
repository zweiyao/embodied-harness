# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Explicit publish/replay command for the manual workbench; never selects tools."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from robots.libero.research.library import Sandbox
from robots.libero.research.sensors import SensorInterface
from rpent.dashboard.workbench import publish, stamp, write_json
from rpent.session import EnvState


def recorded_frames(root, step=None):
    root = Path(root)
    records = json.loads((root / "states.json").read_text())["steps"]
    if step is not None:
        records = [r for r in records if r["step_idx"] <= step]
    if not records:
        raise ValueError("No observation at the requested step")
    selected = records[-4:]
    store = EnvState(root)  # Explicit-step reads only; does not rewrite history.
    proxy = SimpleNamespace(
        load=store.load, records=lambda: [SimpleNamespace(**r) for r in selected]
    )
    sensor = SensorInterface(
        SimpleNamespace(state=proxy, list_tools=lambda: []), [], None
    )
    for r in selected:
        n = r["step_idx"]
        for name in r["artifacts"]:
            if not (
                name.endswith("_alignment.json")
                or (name.startswith("mask_alignment_") and name.endswith(".json"))
            ):
                continue
            alignment = store.load(name, step=n)
            mask = store.load(alignment["mask_artifact"], step=n)
            h, w = store.load(alignment["camera"] + ".png", step=n).shape[:2]
            if list(mask.shape) != alignment["source_shape"]:
                raise ValueError("Recorded mask alignment mismatch")
            rows = np.minimum(
                ((np.arange(h) + 0.5) * mask.shape[0] / h).astype(int),
                mask.shape[0] - 1,
            )
            cols = np.minimum(
                ((np.arange(w) + 0.5) * mask.shape[1] / w).astype(int),
                mask.shape[1] - 1,
            )
            sensor.masks.setdefault(n, {})[alignment["mask_artifact"]] = {
                **alignment,
                "mask": mask[rows[:, None], cols[None, :]],
            }
    return sensor.frames()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True)
    parser.add_argument(
        "--candidate", required=True, help="JSON: name, description, parameters, source"
    )
    parser.add_argument(
        "--metadata",
        required=True,
        help="JSON: source_run, reason, input_contract, optional previous_version",
    )
    parser.add_argument("--replay-run")
    parser.add_argument(
        "--params", default="{}", help="JSON arguments for history replay"
    )
    parser.add_argument("--step", type=int)
    parser.add_argument("--image", default="embodied-sensor:pilot")
    args = parser.parse_args()
    tool = json.loads(Path(args.candidate).read_text())
    metadata = json.loads(Path(args.metadata).read_text())
    if not metadata.get("source_run") or not metadata.get("reason"):
        parser.error("metadata must name source_run and reason")
    if args.replay_run:
        frames = recorded_frames(args.replay_run, args.step)
        sandbox = Sandbox(args.image)
        result = sandbox.run(tool, json.loads(args.params), frames)
        metadata.update(
            validation="replay_passed",
            example=result,
            replay={
                "at": stamp(),
                "run": args.replay_run,
                "steps": [f["step"] for f in frames],
                "params": json.loads(args.params),
                "sandbox_image": sandbox.image,
            },
        )
    version = publish(args.library, tool, metadata)
    if args.replay_run:
        # Validation evidence can be added later without changing immutable code.
        path = Path(args.library) / f"{version}.meta.json"
        saved = json.loads(path.read_text())
        saved.update(metadata)
        write_json(path, saved)
    print(
        json.dumps(
            {
                "version": version,
                "validation": metadata.get("validation", "unverified"),
                "selected": False,
            }
        )
    )


if __name__ == "__main__":
    main()
