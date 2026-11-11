# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read-only event census for three Qwen cohorts and Astra comparators."""

import collections
import json
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/zwy/work/embodied_harness/experiments")
OUT = Path("/home/zwy/work/embodied_harness/debug/qwen-root-cause-20261107")
OUT.mkdir(parents=True, exist_ok=True)
ACTIONS = {
    "move_to",
    "move_pose",
    "pi0_pick",
    "pi0_doubled",
    "release",
    "set_gripper",
    "rotate_pitch",
    "rotate_wrist",
}
GEOM = {"segment", "back_project", "view_camera_meta"}


def load(names):
    rows = []
    for n in names:
        rows += json.loads((ROOT / n / "results.json").read_text())
    return [
        r
        for r in rows
        if r.get("classification") != "unexpected"
        and r.get("evaluation_success", r.get("official_success")) is not None
    ]


def t(e):
    return datetime.fromisoformat(e["time"]).timestamp()


def stats(values):
    return (
        {
            "n": len(values),
            "sum": sum(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }
        if values
        else None
    )


mixed = load(["libero10-task-no-memory-dual-20-20261107"])
groups = {
    "qwen_original": load(
        [
            "libero10-task-qwenflash-3000s-50-20261106",
            "libero10-task-qwenflash-1500s-continuation-20261106",
        ]
    ),
    "qwen_short": load(["qwen-minimal-v1-candidate8-20261107"]),
    "qwen_empty": [r for r in mixed if r["lane"] == "qwen"],
    "astra_original": load(
        [
            "libero10-task-astra-50-20261105" + s
            for s in ["", "/continuation", "/resume34", "/resume32"]
        ]
    ),
    "astra_empty": [r for r in mixed if r["lane"] == "astra"],
}
output = {}
for group, rows in groups.items():
    records = []
    all_latencies = []
    all_tools = collections.Counter()
    errors = collections.Counter()
    for row in rows:
        root = Path(row["path"])
        events = [
            json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()
        ]
        requests = {}
        calls = []
        responses = {}
        latencies = []
        pending = None
        response_text = []
        tool_seconds = []
        for e in events:
            p = e["payload"]
            kind = e["kind"]
            if kind == "model_request":
                pending = t(e)
            elif kind == "model_response":
                if pending is not None:
                    latencies.append(t(e) - pending)
                    pending = None
                response_text.append(
                    " ".join(
                        v.get("content", "")
                        for v in p.get("parts", [])
                        if v.get("part_kind") == "text"
                    )
                )
            elif kind == "tool_request":
                c = {**p, "time": t(e), "index": len(calls)}
                requests[p["call_id"]] = c
                calls.append(c)
            elif kind == "tool_response":
                responses[p["call_id"]] = p
                if p["call_id"] in requests:
                    tool_seconds.append(t(e) - requests[p["call_id"]]["time"])
        first = next((i for i, c in enumerate(calls) if c["name"] in ACTIONS), None)
        before = calls if first is None else calls[:first]
        geom_by_frame = collections.Counter()
        seen = collections.Counter()
        file_errors = []
        valid_segments = []
        bp_errors = []
        for c in calls:
            name = c["name"]
            a = c.get("arguments") or {}
            p = responses.get(c["call_id"], {})
            z = p.get("result") or {}
            if not isinstance(z, dict):
                continue
            if z.get("error") or z.get("errors"):
                errors[name] += 1
                if name == "read_text_file":
                    file_errors.append(
                        {
                            "index": c["index"],
                            "path": a.get("path"),
                            "error": z.get("error"),
                        }
                    )
                if name == "back_project":
                    bp_errors.append({"index": c["index"], "error": z.get("error")})
            if name in GEOM:
                key = json.dumps(
                    {
                        "name": name,
                        "camera": a.get("camera", "agentview"),
                        "step": z.get("step", a.get("step", -1)),
                        **{k: v for k, v in a.items() if k != "step"},
                    },
                    sort_keys=True,
                )
                seen[key] += 1
                if c in before:
                    geom_by_frame[str(z.get("step", a.get("step", -1)))] += 1
            if (
                name == "segment"
                and z.get("found")
                and z.get("world_xyz")
                and not z.get("world_error")
            ):
                valid_segments.append(c["index"])
        all_latencies += latencies
        all_tools.update(c["name"] for c in calls)
        first_kind = calls[first]["name"] if first is not None else None
        record = {
            "task": row["task"],
            "seed": row["seed"],
            "path": str(root),
            "run_id": row["run_id"],
            "success": row.get("evaluation_success", row.get("official_success")),
            "status": row["status"],
            "elapsed_s": row["elapsed_s"],
            "calls": dict(collections.Counter(c["name"] for c in calls)),
            "first_action": first_kind,
            "before_calls": len(before),
            "before_geometry": sum(c["name"] in GEOM for c in before),
            "before_geometry_frames": dict(geom_by_frame),
            "exact_repeated_geometry": sum(n - 1 for n in seen.values()),
            "model_response_latency_s": stats(latencies),
            "model_response_wait_total_s": sum(latencies),
            "unreturned_request_wait_to_end_s": max(0, t(events[-1]) - pending)
            if pending is not None
            else 0,
            "tool_elapsed_sum_s": sum(tool_seconds),
            "first_action_seconds_from_first_event": calls[first]["time"] - t(events[0])
            if first is not None
            else None,
            "first_valid_segment_call": valid_segments[0] if valid_segments else None,
            "geometry_after_first_valid_segment_before_action": sum(
                c["index"] > valid_segments[0] and c["name"] in GEOM for c in before
            )
            if valid_segments
            else None,
            "file_errors": file_errors,
            "back_project_errors": bp_errors,
        }
        records.append(record)
    summary = {
        "runs": len(records),
        "successes": sum(r["success"] for r in records),
        "zero_action": sum(r["first_action"] is None for r in records),
        "first_action_kinds": dict(
            collections.Counter(r["first_action"] for r in records)
        ),
        "calls": dict(all_tools),
        "errors": dict(errors),
        "response_latency_s": stats(all_latencies),
        "tool_elapsed_sum_s": sum(r["tool_elapsed_sum_s"] for r in records),
        "model_response_wait_total_s": sum(
            r["model_response_wait_total_s"] for r in records
        ),
        "unreturned_request_wait_to_end_s": sum(
            r["unreturned_request_wait_to_end_s"] for r in records
        ),
        "file_error_runs": sum(bool(r["file_errors"]) for r in records),
        "before_geometry_started_only": stats(
            [r["before_geometry"] for r in records if r["first_action"] is not None]
        ),
        "exact_repeated_geometry": sum(r["exact_repeated_geometry"] for r in records),
    }
    output[group] = {"summary": summary, "runs": records}
(OUT / "census.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2) + "\n"
)
print(
    json.dumps(
        {k: v["summary"] for k, v in output.items()}, ensure_ascii=False, indent=2
    )
)
