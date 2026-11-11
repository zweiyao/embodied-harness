# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Common tool-event statistics for API and Codex adapters."""

import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

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
OBSERVATIONS = {"view_env_state", "read_image"}
PERCEPTION = {
    "segment",
    "back_project",
    "view_camera_meta",
    "sensor_patch_batch",
    "sensor_container_geometry",
}


def analyze(path, *, audit=True):
    root = Path(path).resolve()
    events = [
        json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()
    ]
    calls = []
    requests = {}
    responses = {}
    bad_reads = []
    model_requests = 0
    for event in events:
        p = event["payload"]
        if event["kind"] == "model_request":
            model_requests += 1
        elif event["kind"] == "tool_request":
            call = {**p, "time": event["time"], "model_request": model_requests}
            requests[p["call_id"]] = call
            calls.append(call)
        elif event["kind"] == "tool_response":
            responses[p["call_id"]] = p
            z = p.get("result")
            if (
                audit
                and p["name"] == "read_text_file"
                and isinstance(z, dict)
                and "content" in z
            ):
                resolved = Path(z.get("path", "")).resolve()
                if not resolved.is_relative_to(root):
                    bad_reads.append({"call_id": p["call_id"], "path": str(resolved)})
    counts = Counter(c["name"] for c in calls)
    first = next((i for i, c in enumerate(calls) if c["name"] in ACTIONS), None)
    before = calls if first is None else calls[:first]
    prefix = Counter(c["name"] for c in before)
    first_response = (
        responses.get(calls[first]["call_id"], {}) if first is not None else {}
    )
    z = first_response.get("result") or {}
    first_executed = (
        isinstance(z, dict)
        and isinstance(z.get("step"), int)
        and z["step"] > 0
        and bool((z.get("log") or {}).get("command"))
    )
    errors = sum(
        isinstance(p.get("result"), dict)
        and bool(p["result"].get("error") or p["result"].get("errors"))
        for p in responses.values()
    )
    seconds = None
    if first is not None:
        seconds = (
            datetime.fromisoformat(calls[first]["time"])
            - datetime.fromisoformat(events[0]["time"])
        ).total_seconds()
    return {
        "tool_calls": dict(counts),
        "all_calls": len(calls),
        "action_calls": sum(counts[n] for n in ACTIONS),
        "has_action_call": first is not None,
        "first_action_confirmed_executed": bool(first_executed),
        "first_action_tool": calls[first]["name"] if first is not None else None,
        "before_action_calls": len(before) if first is not None else None,
        "before_action_observations": sum(prefix[n] for n in OBSERVATIONS)
        if first is not None
        else None,
        "before_action_perception": sum(prefix[n] for n in PERCEPTION)
        if first is not None
        else None,
        "before_action_file_reads": prefix["read_text_file"]
        if first is not None
        else None,
        "prefix_or_no_action_calls": dict(prefix),
        "first_action_seconds_since_first_event": seconds,
        "first_action_model_request": calls[first]["model_request"]
        if first is not None and model_requests
        else None,
        "tool_error_responses": errors,
        "memory_audit_passed": not bad_reads if audit else None,
        "outside_run_reads": bad_reads,
    }


def summarize(rows):
    acting = [r for r in rows if r["metrics"]["has_action_call"]]
    result = {
        "completed": len(rows),
        "successes": sum(r["evaluation_success"] is True for r in rows),
        "with_action": len(acting),
        "without_action": len(rows) - len(acting),
        "first_action_not_confirmed": sum(
            not r["metrics"]["first_action_confirmed_executed"] for r in acting
        ),
    }
    for key in [
        "before_action_observations",
        "before_action_calls",
        "before_action_perception",
        "before_action_file_reads",
    ]:
        values = [r["metrics"][key] for r in acting]
        result[key] = {
            "n": len(values),
            "mean": statistics.mean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }
    return result
