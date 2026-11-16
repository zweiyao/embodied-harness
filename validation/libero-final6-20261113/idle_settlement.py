# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Recognize an approved early-stop failure without adding a model turn."""


def early_stop_evidence(state, events):
    """Return evidence only after a complete, action-free final response."""
    if (
        state.get("session_state") != "running"
        or state.get("interaction", {}).get("planner_activity") != "idle"
        or state.get("terminated") is not False
        or state.get("error")
        or state.get("pending_task")
    ):
        return None
    requests = [e for e in events if e["kind"] == "model_request"]
    responses = [e for e in events if e["kind"] == "model_response"]
    if not requests or len(requests) != len(responses):
        return None
    last = responses[-1]["payload"]
    if last.get("state") != "complete" or last.get("finish_reason") != "stop":
        return None
    parts = last.get("parts", [])
    if not any(p.get("part_kind") == "text" for p in parts):
        return None
    if any(p.get("part_kind") == "tool-call" for p in parts):
        return None
    calls = [e["payload"] for e in events if e["kind"] == "tool_request"]
    returns = [e["payload"] for e in events if e["kind"] == "tool_response"]
    if (
        len(calls) != len(returns)
        or {c["call_id"] for c in calls} != {r["call_id"] for r in returns}
        or any(c["name"] == "finish" for c in calls)
    ):
        return None
    return {
        "classification": "model_stopped_without_finish",
        "environment_success": False,
        "official_signal_source": "latest environment-step terminated flag",
        "model_requests": len(requests),
        "model_responses": len(responses),
        "tool_requests": len(calls),
        "tool_responses": len(returns),
        "finish_reason": last["finish_reason"],
        "response_state": last["state"],
        "last_model_response_time": responses[-1]["time"],
        "followup_prompt_sent": False,
        "raw_outcome_preserved": True,
    }
