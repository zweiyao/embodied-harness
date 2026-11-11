# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Compare initial camera pixels with the existing Flash reference, read-only."""

import hashlib
import json
from pathlib import Path

import numpy as np

from rpent.session import EnvState

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / "plan.json").read_text())
old = json.loads((Path(plan["reference_root"]) / "results.json").read_text())
rows = []
for lane in plan["lanes"]:
    for path in (ROOT / lane / "runs").glob("*/tasks/*"):
        if not (path / "states.json").exists():
            continue
        task = json.loads((path / "dashboard_config.json").read_text())["task"]["task"]
        ref = next(r for r in old if r["task"] == task)
        current, previous = EnvState(path), EnvState(Path(ref["path"]))
        cameras = {}
        for name in ["agentview_high.png", "wrist_high.png"]:
            a, b = current.load(name, step=0), previous.load(name, step=0)
            assert a.shape == b.shape
            different = np.any(a != b, axis=-1)
            cameras[name] = {
                "same_pixels": bool(np.array_equal(a, b)),
                "different_pixel_percent": float(different.mean() * 100),
                "current_sha256": hashlib.sha256(
                    current.load_bytes(name, step=0)
                ).hexdigest(),
                "reference_sha256": hashlib.sha256(
                    previous.load_bytes(name, step=0)
                ).hexdigest(),
            }
        rows.append(
            {
                "task": task,
                "seed": 0,
                "cameras": cameras,
                "matched_initial_images": all(
                    c["same_pixels"] for c in cameras.values()
                ),
            }
        )
report = {
    "rows": sorted(rows, key=lambda r: r["task"]),
    "complete": len(rows) == plan["total"],
    "limitation": "Matching initial images is necessary for a paired scene comparison, not sufficient to establish a causal tool benefit.",
}
(ROOT / "initial-scene-parity.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
