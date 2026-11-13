# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Check early-stop detection, especially outstanding network/tool calls."""

import copy
import json
from pathlib import Path

from idle_settlement import early_stop_evidence

state = {
    "session_state": "running",
    "interaction": {"planner_activity": "idle"},
    "terminated": False,
}
response = {
    "kind": "model_response",
    "time": "2026-11-13T00:00:00Z",
    "payload": {
        "state": "complete",
        "finish_reason": "stop",
        "parts": [{"part_kind": "text", "content": "I will move next."}],
    },
}
events = [{"kind": "model_request", "payload": {}}, response]
assert (
    early_stop_evidence(state, events)["classification"]
    == "model_stopped_without_finish"
)
assert (
    early_stop_evidence(state, events + [{"kind": "model_request", "payload": {}}])
    is None
)
assert (
    early_stop_evidence(
        state,
        events
        + [{"kind": "tool_request", "payload": {"call_id": "x", "name": "move_to"}}],
    )
    is None
)
assert early_stop_evidence({**state, "terminated": True}, events) is None
assert early_stop_evidence({**state, "terminated": None}, events) is None
assert (
    early_stop_evidence({**state, "interaction": {"planner_activity": "busy"}}, events)
    is None
)
assert early_stop_evidence({**state, "session_state": "ready"}, events) is None
assert early_stop_evidence({**state, "error": "network error"}, events) is None
assert early_stop_evidence(state, []) is None
for field, value in [
    ("state", "incomplete"),
    ("finish_reason", "length"),
    ("parts", [{"part_kind": "tool-call"}]),
]:
    changed = copy.deepcopy(events)
    changed[-1]["payload"][field] = value
    assert early_stop_evidence(state, changed) is None
calls = [
    {"kind": "tool_request", "payload": {"call_id": "x", "name": "finish"}},
    {"kind": "tool_response", "payload": {"call_id": "x", "name": "finish"}},
]
assert early_stop_evidence(state, calls + events) is None
calls[0]["payload"]["name"] = "move_to"
calls[1]["payload"]["name"] = "move_to"
assert early_stop_evidence(state, calls + events) is not None
calls[1]["payload"]["call_id"] = "different"
assert early_stop_evidence(state, calls + events) is None

base = Path("/home/zwy/work/embodied_harness")
preflight = json.loads(
    (base / "validation/robodojo-astra-task0-20261113/preflight.json").read_text()
)
old = (
    base
    / "experiments/libero-object-t-qwenflash-original-50-ipv4-resume-20261113/b/runs"
)
path = next(old.rglob("*libero_object_task_t8_s1/events.jsonl"))
real = [json.loads(line) for line in path.read_text().splitlines()]
evidence = early_stop_evidence(preflight["states"]["37391"], real)
assert evidence and evidence["model_requests"] == 11 and evidence["tool_requests"] == 17
assert early_stop_evidence(preflight["states"]["48873"], real) is None
report = {
    "status": "passed",
    "synthetic_checks": 15,
    "historical_checks": 2,
    "pending_network_and_tools_never_settled_as_early_stop": True,
    "historical_idle": evidence,
}
(Path(__file__).resolve().parent / "idle-settlement-check.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
print(json.dumps(report), flush=True)
