# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read saved 03–05 images/events only; print small coordinate-audit metadata."""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

BASE = Path("/home/zwy/work/embodied_harness/experiments/qwen-continuous-20261109")
report = {"runs": [], "patch_calls": 0, "patch_points": 0, "recorded_frames": 0}
for iteration in ("03", "04", "05"):
    for lane in "ab":
        run = next(
            (BASE / f"iteration-{iteration}" / lane).glob("runs/session/tasks/*")
        )
        events = [
            json.loads(s) for s in (run / "events.jsonl").read_text().splitlines()
        ]
        row = {
            "iteration": iteration,
            "lane": lane,
            "orientation": {},
            "mirrored_recorded_frames": 0,
        }
        for policy_file in sorted((run / "agentview_policy.png").glob("*.png")):
            policy = np.asarray(Image.open(policy_file))
            calibrated = np.asarray(
                Image.open(run / "agentview.png" / policy_file.name)
            )
            assert np.array_equal(policy, calibrated[:, ::-1])
            row["mirrored_recorded_frames"] += 1
            report["recorded_frames"] += 1
        files = {}
        for name in (
            "agentview_policy.png",
            "agentview.png",
            "agentview_high.png",
            "wrist.png",
            "wrist_high.png",
        ):
            path = run / name / "00.png"
            files[hashlib.sha256(path.read_bytes()).hexdigest()] = {
                "artifact": name,
                "size_wh": Image.open(path).size,
            }
        for camera in ("agentview", "wrist"):
            low = np.asarray(Image.open(run / f"{camera}.png/00.png"))
            high = np.asarray(
                Image.open(run / f"{camera}_high.png/00.png").resize(
                    (256, 256), Image.Resampling.BOX
                )
            )
            row["orientation"][camera + "_high_to_low_MAE"] = {
                name: round(float(np.abs(low.astype(float) - image).mean()), 4)
                for name, image in [
                    ("same", high),
                    ("horizontal", high[:, ::-1]),
                    ("vertical", high[::-1]),
                    ("both", high[::-1, ::-1]),
                ]
            }
        for ordinal, event in enumerate(
            (e for e in events if e["kind"] == "model_request"), 1
        ):
            binaries = []

            def visit(value):
                if isinstance(value, dict):
                    if value.get("kind") == "binary":
                        binaries.append(value)
                        return
                    for item in value.values():
                        visit(item)
                elif isinstance(value, list):
                    for item in value:
                        visit(item)

            visit(event["payload"])
            if binaries:
                row["first_images_request"] = ordinal
                row["supplied_images"] = [
                    files[
                        hashlib.sha256(
                            (run / b["data"]["artifact"]).read_bytes()
                        ).hexdigest()
                    ]
                    for b in binaries
                ]
                row["binary_identifiers_absent"] = all(
                    b.get("_identifier") is None and b.get("vendor_metadata") is None
                    for b in binaries
                )
                break
        for event in events:
            if (
                event["kind"] == "tool_response"
                and event["payload"].get("name") == "sensor_patch_batch"
            ):
                result = event["payload"]["result"]
                report["patch_calls"] += 1
                for point in result.get("patches", []):
                    height, width = result["image_size"]
                    expected = [
                        round(point["point_rc_normalized"][0] * (height - 1)),
                        round(point["point_rc_normalized"][1] * (width - 1)),
                    ]
                    assert expected == point["pixel_rc"]
                    report["patch_points"] += 1
        report["runs"].append(row)
report["all_checked_patch_conversions_match"] = True
report["all_recorded_policy_images_exact_horizontal_mirrors"] = True
report["model_requests_issued_by_audit"] = 0
report["simulator_actions"] = 0
report["source_hashes"] = {}
producer = Path(
    "/home/zwy/work/harnessvla/.venv/lib/python3.11/site-packages/rlinf/envs/sim/libero"
)
for path in [producer / "libero_env.py", producer / "utils.py"]:
    report["source_hashes"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
for iteration in ("03", "04", "05"):
    plan = json.loads((BASE / f"iteration-{iteration}/plan.json").read_text())
    for name in (
        "robots/libero/tools.py",
        "robots/libero/toolkit.py",
        "rpent/planner/api_loop.py",
    ):
        path = Path(plan["runtime_source"]) / name
        report["source_hashes"][str(path)] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
print(json.dumps(report, indent=2))
