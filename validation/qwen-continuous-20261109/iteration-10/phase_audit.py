# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Check workflow exposure against recorded execution, without judging success."""

from robots.libero.research.manual import (
    INITIAL_ACTION_PRIMITIVES,
    INITIAL_ACTION_TOOLS,
)


def audit_phase(events, states, full_tools):
    steps = {s["step_idx"]: s for s in states}
    pending = {}
    unlocked = False
    requests = []
    transition = None
    for event in events:
        kind, payload = event["kind"], event["payload"]
        if kind == "tool_request":
            if not unlocked:
                assert payload["name"] in INITIAL_ACTION_TOOLS, "Pre-phase dispatch"
            pending[payload["call_id"]] = payload["name"]
        elif kind == "workflow_phase":
            assert not unlocked, "Repeated phase transition"
            assert payload["phase"] == "manual_available"
            name, step = payload["trigger"], payload["after_step"]
            assert name in INITIAL_ACTION_PRIMITIVES and name in pending.values()
            state = steps[step]
            assert state["command"]["action"] == name
            assert state["result"]["chunks_used"] > 0
            transition = {
                "step": step,
                "trigger": name,
                "chunks_used": state["result"]["chunks_used"],
            }
            unlocked = True
        elif kind == "tool_response":
            name = pending.pop(payload["call_id"])
            assert name == payload["name"]
            step = payload.get("result", {}).get("step")
            if name in INITIAL_ACTION_PRIMITIVES and step in steps:
                state = steps[step]
                if (state.get("command") or {}).get("action") == name and (
                    state.get("result") or {}
                ).get("chunks_used", 0) > 0:
                    assert unlocked, "Missing phase transition after actual execution"
        elif kind == "model_request":
            params = payload["model_request_parameters"]
            actual = params["function_tools"] + params["output_tools"]
            expected = (
                full_tools
                if unlocked
                else [t for t in full_tools if t["name"] in INITIAL_ACTION_TOOLS]
            )
            assert actual == expected, "Wrong phase exposure or schema"
            requests.append(
                {
                    "request": len(requests) + 1,
                    "phase": "manual_available" if unlocked else "initial",
                    "tool_names": [t["name"] for t in actual],
                }
            )
    assert requests and requests[0]["phase"] == "initial"
    return {
        "passed": True,
        "requests": requests,
        "transition": transition,
        "limit": "Phase/dispatch evidence only; no success, holding or outcome-classification inference.",
    }
