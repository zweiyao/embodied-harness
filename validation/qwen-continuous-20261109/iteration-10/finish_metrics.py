# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Observe finish-only API behavior without influencing the experiment outcome."""

from collections import Counter


def analyze_finish(events):
    gate_values = Counter()
    responses = Counter()
    finish_attempts = 0
    entries, returns, retries = [], {}, []
    pending_text = None
    request_number = 0
    for event in events:
        payload = event["payload"]
        if event["kind"] == "model_request":
            request_number += 1
            gate = payload["model_request_parameters"].get("allow_text_output")
            gate_values[str(gate)] += 1
            if pending_text is not None and gate is False:
                messages = payload.get("messages", [])
                feedback = [
                    part
                    for part in (messages[-1].get("parts", []) if messages else [])
                    if part.get("part_kind") == "retry-prompt"
                    and part.get("tool_name") is None
                ]
                for part in feedback:
                    content = part.get("content")
                    retries.append(
                        {
                            "rejected_response_request": pending_text,
                            "following_request": request_number,
                            "feedback": content[:500]
                            if isinstance(content, str)
                            else "non_string_feedback",
                        }
                    )
            pending_text = None
        elif event["kind"] == "model_response":
            parts = payload["parts"]
            calls = [p for p in parts if p.get("part_kind") == "tool-call"]
            text = any(p.get("part_kind") == "text" and p.get("content") for p in parts)
            kind = (
                "mixed_text_and_tool_calls"
                if text and calls
                else "tool_calls_only"
                if calls
                else "pure_text"
                if text
                else "other"
            )
            responses[kind] += 1
            finish_attempts += sum(p.get("tool_name") == "finish" for p in calls)
            pending_text = request_number if kind == "pure_text" else None
        elif event["kind"] == "tool_request" and payload.get("name") == "finish":
            entries.append(payload)
        elif event["kind"] == "tool_response" and payload.get("name") == "finish":
            returns[payload["call_id"]] = payload
    finish_returns = []
    for call in entries:
        returned = returns.get(call["call_id"])
        result = returned.get("result") if returned else None
        result = result if isinstance(result, dict) else {}
        finish_returns.append(
            {
                "call_id": call["call_id"],
                "returned": returned is not None,
                "accepted_finish_flag": result.get("_finish") is True,
                "return_error": bool(
                    (returned or {}).get("error")
                    or result.get("error")
                    or result.get("errors")
                ),
                "return_code": result.get("code"),
            }
        )
    return {
        "actual_allow_text_output_counts": dict(gate_values),
        "completed_response_kinds": dict(responses),
        "finish_model_attempts": finish_attempts,
        "finish_toolkit_entries": len(entries),
        "finish_returns": finish_returns,
        "accepted_finish_returns": sum(
            r["accepted_finish_flag"] for r in finish_returns
        ),
        "pure_text_followed_by_output_retry": retries,
        "last_pure_text_without_followup_request": pending_text,
        "limit": "Observational only. Toolkit entry precedes handler validation; accepted finish is not official success. Retry feedback is associated with the immediately preceding pure-text response and a false allow_text_output gate, without changing classification or budgets.",
    }


def safe_finish_metrics(events):
    try:
        return analyze_finish(events)
    except Exception as exc:
        return {"metric_error": type(exc).__name__, "classification_unchanged": True}
