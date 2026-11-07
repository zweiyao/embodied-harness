# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Recompute final adoption and timing evidence without replaying any action."""

import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from run_batch import PLAN, ROOT, analyze, save, unchanged

rows = json.loads((ROOT / "results.json").read_text())
assert len(rows) == 3
assert {(r["task"], r["seed"]) for r in rows} == {(0, 0), (4, 0), (8, 0)}
assert all(
    r["classification"] != "unexpected" and type(r["evaluation_success"]) is bool
    for r in rows
)
unchanged()
details = []
for row in rows:
    path = Path(row["path"])
    recomputed = analyze(path)
    for key in [
        "before_action_calls",
        "action_calls",
        "all_calls",
        "memory_audit_passed",
    ]:
        assert recomputed[key] == row["metrics"][key]
    events = [
        json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()
    ]
    latencies, calls, statuses = [], [], Counter()
    pending = None
    index_visible = False
    patch_points = 0
    for event in events:
        payload = event["payload"]
        stamp = datetime.fromisoformat(event["time"]).timestamp()
        if event["kind"] == "model_request":
            pending = stamp
        elif event["kind"] == "model_response" and pending is not None:
            latencies.append(stamp - pending)
            pending = None
        elif event["kind"] == "tool_request":
            calls.append(payload)
            if payload["name"] == "sensor_patch_batch":
                patch_points += len(payload.get("arguments", {}).get("points", []))
        elif event["kind"] == "tool_response":
            result = payload.get("result")
            if not isinstance(result, dict):
                continue
            if payload["name"] == "sensor_container_geometry":
                statuses[result.get("status", result.get("error", "unknown"))] += 1
            if (
                payload["name"] == "read_text_file"
                and Path(result.get("path", "")).name == "MEMORY.md"
            ):
                content = str(result.get("content", ""))
                index_visible |= all(
                    name in content
                    for name in [
                        "next-action-evidence.md",
                        "object-relative-transfer.md",
                    ]
                )
    details.append(
        {
            "task": row["task"],
            "seed": row["seed"],
            "path": str(path),
            "evaluation_success": row["evaluation_success"],
            "status": row["status"],
            "elapsed_s": row["elapsed_s"],
            "all_tool_calls": len(calls),
            "action_calls": recomputed["action_calls"],
            "before_action_calls": recomputed["before_action_calls"],
            "new_experience_bodies_read": row["metrics"]["new_experience_reads"],
            "new_entries_visible_in_read_index": index_visible,
            "generated_tool_calls": row["metrics"]["generated_tool_calls"],
            "batch_point_count": patch_points,
            "container_statuses": dict(statuses),
            "returned_model_requests": len(latencies),
            "returned_request_wait_mean_s": statistics.mean(latencies)
            if latencies
            else None,
            "returned_request_wait_median_s": statistics.median(latencies)
            if latencies
            else None,
            "model_wait_sum_returned_s": sum(latencies),
            "unfinished_request_at_end": pending is not None,
            "tool_error_responses": recomputed["tool_error_responses"],
        }
    )
incidents = sum(len(json.loads(p.read_text())) for p in ROOT.glob("*/incidents.json"))
cleanup = json.loads((ROOT / "cleanup.json").read_text())
assert cleanup["passed"]
report = {
    "passed": True,
    "completed": len(rows),
    "planned": PLAN["total"],
    "successes": sum(r["evaluation_success"] for r in rows),
    "success_rate_percent": 100
    * sum(r["evaluation_success"] for r in rows)
    / len(rows),
    "unexpected_incidents": incidents,
    "source_hashes_unchanged": True,
    "conditional_first_action_metrics_recomputed": True,
    "cleanup_passed": True,
    "details": details,
    "limitations": "Three selected cells, parallel direct-network candidate only. Timing is request/response elapsed, not pure network. No causal baseline or task-gain proof.",
}
save(ROOT / "final-verification.json", report)
print(json.dumps(report, ensure_ascii=False, indent=2))
