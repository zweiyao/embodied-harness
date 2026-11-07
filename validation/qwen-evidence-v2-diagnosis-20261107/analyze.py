# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read-only numerical replay and event audit of the three approved episodes."""

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path("/home/zwy/work/embodied_harness")
BATCH = ROOT / "experiments/qwen-evidence-v2-screen3-20261107"
VERSION = "cca2f3c424d195fe3e55896ec0fe4c54b08b9f6929fdf794cfc98595458155c3"
library = ROOT / f"tool-library/manual/{VERSION}.json"
assert (
    hashlib.sha256(library.read_bytes()).hexdigest()
    == "ae4d062e8810352fa3c36e78326d1e6e40faac77917fdb68ec2356f311fd18a9"
)
tool = json.loads(library.read_text())[0]
namespace = {}
exec(compile(tool["source"], str(library), "exec"), namespace)  # noqa: S102
run = namespace["run"]
report = {"published_version": VERSION, "episodes": [], "new_environment_actions": 0}


def array(path):
    with np.load(path) as data:
        assert len(data.files) == 1
        return data[data.files[0]]


for row in json.loads((BATCH / "results.json").read_text()):
    path = Path(row["path"])
    events = [
        json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()
    ]
    states = json.loads((path / "states.json").read_text())["steps"]
    frames = {}
    for state in states:
        step = state["step_idx"]
        name = f"{step:02d}"
        frames[step] = {
            "step": step,
            "proprio": state["state"],
            "cameras": {
                "agentview": {
                    "high": {
                        "rgb": np.asarray(
                            Image.open(path / f"agentview_high.png/{name}.png")
                        ),
                        "world": array(path / f"agentview_world_high.npz/{name}.npz"),
                        "depth": array(path / f"agentview_depth_high.npz/{name}.npz"),
                    }
                }
            },
        }
    stats = {
        "task": row["task"],
        "run_id": row["run_id"],
        "reads": [],
        "actions": [],
        "model_requests_carrying_index": 0,
        "patch_calls": 0,
        "patch_points": 0,
        "failed_points": 0,
        "calls_with_failed_points": 0,
        "radius_zero_calls": 0,
        "numerical_medians_verified": 0,
        "duplicate_samples": 0,
        "tool_elapsed_sum_s": 0,
        "model_response_elapsed_sum_s": 0,
        "model_responses": 0,
        "batch_return_chars": 0,
        "timing_pairs": [],
        "radius_counts": Counter(),
    }
    seen = set()
    calls = {}
    pending = None
    for index, event in enumerate(events):
        kind, payload = event["kind"], event["payload"]
        stamp = datetime.fromisoformat(event["time"]).timestamp()
        if kind == "model_request":
            serialized = json.dumps(payload)
            stats["model_requests_carrying_index"] += all(
                name in serialized
                for name in ["next-action-evidence.md", "object-relative-transfer.md"]
            )
            pending = stamp
        elif kind == "model_response" and pending is not None:
            elapsed = stamp - pending
            stats["model_response_elapsed_sum_s"] += elapsed
            stats["model_responses"] += 1
            stats["timing_pairs"].append(
                {
                    "elapsed_s": round(elapsed, 3),
                    "input_tokens": payload["usage"]["input_tokens"],
                }
            )
            pending = None
        elif kind == "tool_request":
            calls[payload["call_id"]] = payload
        elif kind == "tool_response":
            result = payload["result"]
            stats["tool_elapsed_sum_s"] += payload.get("elapsed_s", 0)
            if payload["name"] == "read_text_file":
                content = result.get("content", "")
                stats["reads"].append(
                    {
                        "file": Path(result["path"]).name,
                        "chars": len(content),
                        "event_line": index + 1,
                    }
                )
                if Path(result["path"]).name == "MEMORY.md":
                    stats["index_entry_count"] = content.count("](")
                    stats["new_index_entries_visible"] = all(
                        n in content
                        for n in [
                            "next-action-evidence.md",
                            "object-relative-transfer.md",
                        ]
                    )
            elif payload["name"] == "move_to":
                actual = result["log"]["result"]
                stats["actions"].append(
                    {
                        "event_line": index + 1,
                        "residual_m": actual["final_dist_m"],
                        "steps_used": actual["steps_used"],
                        "max_steps": actual["max_steps"],
                        "gripper": result["log"]["command"]["gripper"],
                    }
                )
            elif payload["name"] == "sensor_patch_batch":
                args = calls[payload["call_id"]]["arguments"]
                radius = args.get("radius", 2)
                stats["radius_counts"][radius] += 1
                stats["patch_calls"] += 1
                stats["radius_zero_calls"] += radius == 0
                stats["batch_return_chars"] += len(json.dumps(result))
                step = result["step"]
                frame = frames[step]
                replay = run([frame], {**args, "step": step})
                assert replay["patches"] == result["patches"]
                failed = 0
                for patch in result["patches"]:
                    stats["patch_points"] += 1
                    r, c = patch["pixel_rc"]
                    key = (step, r, c, radius)
                    stats["duplicate_samples"] += key in seen
                    seen.add(key)
                    if "error" in patch:
                        stats["failed_points"] += 1
                        failed += 1
                        assert radius == 0 and patch["valid_count"] == 1
                        continue
                    data = frame["cameras"]["agentview"]["high"]
                    xyz = data["world"][
                        max(0, r - radius) : r + radius + 1,
                        max(0, c - radius) : c + radius + 1,
                        :3,
                    ].reshape(-1, 3)
                    z = data["depth"][
                        max(0, r - radius) : r + radius + 1,
                        max(0, c - radius) : c + radius + 1,
                    ].reshape(-1)
                    good = (
                        np.isfinite(xyz).all(axis=1)
                        & (np.abs(xyz).sum(axis=1) > 1e-6)
                        & np.isfinite(z)
                        & (z > 0)
                    )
                    np.testing.assert_allclose(
                        patch["world_median_xyz"], np.median(xyz[good], axis=0)
                    )
                    stats["numerical_medians_verified"] += 1
                stats["calls_with_failed_points"] += failed > 0
    stats["patch_replay_matches"] = True
    stats["model_wait_mean_s"] = (
        stats["model_response_elapsed_sum_s"] / stats["model_responses"]
    )
    stats["model_wait_fraction_of_budget"] = stats["model_response_elapsed_sum_s"] / 300
    report["episodes"].append(stats)

# Minimal counterexample: every pixel valid, but the advertised radius=0 cannot pass.
frame = {
    "step": 0,
    "proprio": {"robot0_eef_pos": [0.0, 0.0, 0.0]},
    "cameras": {
        "agentview": {
            "high": {
                "rgb": np.full((5, 5, 3), 100, dtype=np.uint8),
                "world": np.ones((5, 5, 3)),
                "depth": np.ones((5, 5)),
            }
        }
    },
}
zero = run([frame], {"points": [[0.5, 0.5]], "radius": 0})["patches"][0]
one = run([frame], {"points": [[0.5, 0.5]], "radius": 1})["patches"][0]
assert zero["valid_count"] == 1 and "error" in zero
assert one["valid_count"] == 9 and "world_median_xyz" in one
report["radius_zero_counterexample"] = {
    "declared_minimum": 0,
    "valid_input_count": zero["valid_count"],
    "actual_error": zero["error"],
    "same_frame_radius_one_succeeds": True,
}
report["limits"] = (
    "Numerical replay validates sampled arrays, not semantic point selection or physical calibration. Timing is request/response elapsed, not pure network. No new model or simulator experiment."
)
report["result_validity"] = {
    "raw_recorded_successes": 0,
    "raw_recorded_attempts": 3,
    "tool_defect_affected_tasks": [
        e["task"] for e in report["episodes"] if e["radius_zero_calls"]
    ],
    "unaffected_tasks": [
        e["task"] for e in report["episodes"] if not e["radius_zero_calls"]
    ],
    "clean_unaffected_successes": 0,
    "clean_unaffected_attempts": 2,
    "affected_attempt_preserved": True,
    "replacement_pending_approval": True,
}
output = Path(__file__).with_name("summary.json")
output.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
