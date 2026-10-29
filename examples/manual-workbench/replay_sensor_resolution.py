# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Compare actual high/low surfaces and replay candidates without publishing."""

import argparse
import json
from pathlib import Path

import numpy as np

from robots.libero.research.library import Sandbox
from robots.libero.research.manual_library import recorded_frames
from rpent.session import EnvState


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--step", type=int, default=0)
    parser.add_argument("--camera", choices=["agentview", "wrist"], default="agentview")
    parser.add_argument("--row", type=int, default=525)
    parser.add_argument("--col", type=int, default=555)
    parser.add_argument("--image", default="embodied-sensor:pilot")
    args = parser.parse_args()
    frames = recorded_frames(args.run, args.step)
    frame = next(f for f in frames if f["step"] == args.step)
    data = frame["cameras"][args.camera]
    if "high" not in data:
        parser.error("the selected recorded frame has no actual high-resolution pair")
    high, low = data["high"]["world"], data["world"]
    h, w = high.shape[:2]
    if not (0 <= args.row < h and 0 <= args.col < w):
        parser.error("row/col is outside the recorded high-resolution image")
    low_row = min(low.shape[0] - 1, int((args.row + 0.5) * low.shape[0] / h))
    low_col = min(low.shape[1] - 1, int((args.col + 0.5) * low.shape[1] / w))
    high_xyz = high[args.row, args.col].astype(float)
    low_xyz = low[low_row, low_col].astype(float)
    store = EnvState(args.run)
    output = {
        "run": str(args.run.resolve()),
        "step": args.step,
        "camera": args.camera,
        "coordinates": "[row,col] image pixels; world XYZ metres",
        "high": {
            "pixel_rc": [args.row, args.col],
            "world_xyz": high_xyz.tolist(),
            "dtype": str(high.dtype),
            "source": str(
                store.artifact_path(f"{args.camera}_world_high.npz", step=args.step)
            ),
        },
        "previous_low_mapping": {
            "pixel_rc": [low_row, low_col],
            "world_xyz": low_xyz.tolist(),
            "dtype": str(low.dtype),
            "source": str(
                store.artifact_path(f"{args.camera}_world.npz", step=args.step)
            ),
        },
        "surface_difference_m": float(np.linalg.norm(high_xyz - low_xyz)),
    }
    examples = Path(__file__).resolve().parent
    sandbox = Sandbox(args.image)
    candidate = json.loads((examples / "candidate.json").read_text())
    output["patch_replay"] = sandbox.run(
        candidate,
        {
            "step": args.step,
            "camera": args.camera,
            "points": [[args.row / (h - 1), args.col / (w - 1)]],
            "radius": 1,
        },
        frames,
    )
    output["container_replays"] = []
    candidate = json.loads((examples / "container_candidate.json").read_text())
    with (args.run / "events.jsonl").open() as events:
        for line in events:
            event = json.loads(line)
            payload = event.get("payload", {})
            if (
                event.get("kind") != "generated_input"
                or payload.get("name") != candidate["name"]
            ):
                continue
            params = payload["params"]
            selected_step = params.get("step", -1)
            if selected_step == -1:
                selected_step = payload["steps"][-1]
            if (
                selected_step == args.step
                and params.get("camera", "agentview") == args.camera
            ):
                output["container_replays"].append(
                    {
                        "params": params,
                        "result": sandbox.run(
                            candidate, {**params, "step": args.step}, frames
                        ),
                    }
                )
    output["sandbox_image"] = sandbox.image
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
