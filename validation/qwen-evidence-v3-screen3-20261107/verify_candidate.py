# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Check the approved patch against archived results without simulator actions."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from metrics import analyze

from robots.libero.research.manual_library import recorded_frames

root = Path(__file__).resolve().parent
base = Path("/home/zwy/work/embodied_harness")
candidate = json.loads((root / "candidate.json").read_text())
old_path = (
    base
    / "tool-library/manual/cca2f3c424d195fe3e55896ec0fe4c54b08b9f6929fdf794cfc98595458155c3.json"
)
old_hash = hashlib.sha256(old_path.read_bytes()).hexdigest()
old = json.loads(old_path.read_text())[0]
assert (
    candidate["name"] == old["name"] and candidate["description"] == old["description"]
)
namespace = {}
exec(compile(candidate["source"], "approved-candidate", "exec"), namespace)  # noqa: S102
run = namespace["run"]
batch = base / "experiments/qwen-evidence-v2-screen3-20261107"
valid_points = zero_points = calls = 0
checks = []
for row in json.loads((batch / "results.json").read_text()):
    path = Path(row["path"])
    events = [
        json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()
    ]
    requests = {
        e["payload"]["call_id"]: e["payload"]["arguments"]
        for e in events
        if e["kind"] == "tool_request"
    }
    cache = {}
    for event in events:
        p = event["payload"]
        if event["kind"] != "tool_response" or p["name"] != "sensor_patch_batch":
            continue
        args = requests[p["call_id"]]
        result = p["result"]
        step = result["step"]
        if step not in cache:
            cache[step] = recorded_frames(path, step)
        actual = run(cache[step], args)
        if args.get("radius", 2) == 0:
            assert not Draft202012Validator(candidate["parameters"]).is_valid(args)
            assert actual == {
                "error": "radius must be at least 1; use back_project for a single pixel"
            }
            zero_points += len(result["patches"])
        else:
            assert Draft202012Validator(candidate["parameters"]).is_valid(args)
            assert actual["patches"] == result["patches"]
            valid_points += len(result["patches"])
        calls += 1
    stats = analyze(path)
    assert stats["patch_failed_points"] == (20 if row["task"] == 0 else 0)
    assert stats["patch_calls_with_failed_points"] == (4 if row["task"] == 0 else 0)
    assert stats["tool_error_responses"] == 0
    checks.append(
        {
            "task": row["task"],
            "failed_points": stats["patch_failed_points"],
            "container_status_counts": stats["container_status_counts"],
        }
    )
assert (calls, valid_points, zero_points) == (40, 247, 20)
assert hashlib.sha256(old_path.read_bytes()).hexdigest() == old_hash
report = {
    "passed": True,
    "archived_calls": calls,
    "valid_points_identical": valid_points,
    "zero_radius_points_rejected": zero_points,
    "nested_metric_checks": checks,
    "old_published_tool_unchanged": True,
    "new_environment_actions": 0,
}
(root / "candidate-validation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
