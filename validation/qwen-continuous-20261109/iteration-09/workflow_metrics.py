# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Observational W2 public-label metrics; never controls actions or outcomes."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

W2_USER_SHA256 = "c2fcb0c20b6df26c943a04377b9ed064897783fe2559dcc7cab716046bddffe8"
MARKER = re.compile(r"\ANEXT\s*=\s*([A-Za-z_]\w*)\s*;\s*NEED\s*=\s*([^\r\n]+)")
REQUIRED_STARTUP = ("view_env_state", "guide", "index")


def arguments(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def marker(text, enabled_actions):
    text = text.lstrip()
    match = MARKER.match(text)
    if match is None:
        return {"status": "malformed" if text.startswith("NEXT") else "missing"}
    action, need = match.groups()
    need = need.strip()
    return {
        "status": "valid"
        if action in enabled_actions and need
        else "invalid_action_or_need",
        "next": action,
        "need": need[:300],
        "need_truncated": len(need) > 300,
        "need_none": need.lower() == "none",
    }


def analyze_workflow(events, run_path, enabled_actions, *, requested):
    """Group each response and its actual journal calls by model-request ordinal."""
    root = Path(run_path)
    expected_files = {
        "guide": root / "language-materials/guide.md",
        "index": root / "language-materials/memory/MEMORY.md",
    }
    cycles, returns = [], {}
    current = None
    for event in events:
        payload = event["payload"]
        if event["kind"] == "model_request":
            current = {"request": len(cycles) + 1, "response": None, "calls": []}
            cycles.append(current)
        elif event["kind"] == "model_response" and current is not None:
            current["response"] = payload
        elif event["kind"] == "tool_request" and current is not None:
            current["calls"].append(payload)
        elif event["kind"] == "tool_response":
            returns[payload["call_id"]] = payload

    def action_returns(calls):
        rows = []
        for call in calls:
            if call.get("name") not in enabled_actions:
                continue
            returned = returns.get(call["call_id"])
            result = returned.get("result") if returned else None
            code = result.get("code") if isinstance(result, dict) else None
            error = (returned or {}).get("error") or (
                result.get("error") or result.get("errors")
                if isinstance(result, dict)
                else None
            )
            rows.append(
                {
                    "name": call["name"],
                    "call_id": call["call_id"],
                    "return_status": "missing_return"
                    if returned is None
                    else "cancelled"
                    if code == "tool_cancelled"
                    else "error"
                    if error
                    else "returned_without_reported_error",
                    "return_code": code,
                }
            )
        return rows

    def startup_label(name, args):
        if name == "view_env_state":
            return "view_env_state"
        path = args.get("path")
        if name == "read_text_file" and isinstance(path, str):
            return next(
                (
                    label
                    for label, expected in expected_files.items()
                    if Path(path) == expected
                ),
                None,
            )
        return None

    bootstrap = cycles[0] if cycles else {"response": None, "calls": []}
    first_parts = (bootstrap["response"] or {}).get("parts", [])
    attempts = [part for part in first_parts if part.get("part_kind") == "tool-call"]
    attempted = Counter(
        filter(
            None,
            (
                startup_label(p.get("tool_name"), arguments(p.get("args")))
                for p in attempts
            ),
        )
    )
    dispatched = Counter(
        filter(
            None,
            (
                startup_label(p.get("name"), arguments(p.get("arguments")))
                for p in bootstrap["calls"]
            ),
        )
    )
    successful = Counter()
    for call in bootstrap["calls"]:
        returned = returns.get(call["call_id"], {})
        result = returned.get("result")
        if (
            not isinstance(result, dict)
            or returned.get("error")
            or result.get("error")
            or result.get("errors")
        ):
            continue
        if call.get("name") == "view_env_state" and result.get("step") == 0:
            successful["view_env_state"] += 1
        elif call.get("name") == "read_text_file":
            for label, expected in expected_files.items():
                if (
                    result.get("path") == str(expected)
                    and "content" in result
                    and expected.is_file()
                    and result["content"] == expected.read_text()
                ):
                    successful[label] += 1
    first_actions = [
        p["name"] for p in bootstrap["calls"] if p["name"] in enabled_actions
    ]
    grouped_success = all(successful[label] for label in REQUIRED_STARTUP)
    first = {
        "request": 1,
        "response_completed": bootstrap["response"] is not None,
        "attempted_required_counts": dict(attempted),
        "dispatched_required_counts": dict(dispatched),
        "successful_required_counts": dict(successful),
        "three_attempted_together": all(attempted[label] for label in REQUIRED_STARTUP),
        "three_dispatched_together": all(
            dispatched[label] for label in REQUIRED_STARTUP
        ),
        "three_succeeded_together": grouped_success,
        "extra_action_attempts": [
            p["tool_name"] for p in attempts if p.get("tool_name") in enabled_actions
        ],
        "extra_action_dispatches": first_actions,
        "action_returns": action_returns(bootstrap["calls"]),
        "other_dispatches": [
            p["name"]
            for p in bootstrap["calls"]
            if startup_label(p.get("name"), arguments(p.get("arguments"))) is None
        ],
        "grouped_success_without_action": grouped_success
        and not first_actions
        and not any(p.get("tool_name") in enabled_actions for p in attempts),
    }
    measured = []
    for cycle in cycles[1:]:
        response = cycle["response"]
        if response is None:
            continue
        parts = response.get("parts", [])
        text = "\n".join(
            p.get("content", "")
            for p in parts
            if p.get("part_kind") == "text" and isinstance(p.get("content"), str)
        )
        parsed = marker(text, enabled_actions)
        action_attempts = [
            p["tool_name"]
            for p in parts
            if p.get("part_kind") == "tool-call"
            and p.get("tool_name") in enabled_actions
        ]
        action_dispatches = [
            p["name"] for p in cycle["calls"] if p["name"] in enabled_actions
        ]
        none_eligible = parsed["status"] == "valid" and parsed["need_none"]
        measured.append(
            {
                "request": cycle["request"],
                "tag_required": requested,
                **parsed,
                "need_semantics": "not_mechanically_verified",
                "action_attempts": action_attempts,
                "action_dispatches": action_dispatches,
                "action_returns": action_returns(cycle["calls"]),
                "nonaction_dispatches": [
                    p["name"]
                    for p in cycle["calls"]
                    if p["name"] not in enabled_actions
                ],
                "none_action_attempted": parsed["next"] in action_attempts
                if none_eligible
                else None,
                "none_action_dispatched": parsed["next"] in action_dispatches
                if none_eligible
                else None,
                "none_only_matching_action_dispatches": bool(action_dispatches)
                and all(name == parsed["next"] for name in action_dispatches)
                if none_eligible
                else None,
            }
        )
    eligible = [
        row for row in measured if row.get("status") == "valid" and row.get("need_none")
    ]
    return {
        "workflow_requested": requested,
        "parent_tag_interpretation": None if requested else "descriptive_not_requested",
        "bootstrap": first,
        "poststartup_completed_responses": len(measured),
        "required_tag_responses": len(measured) if requested else 0,
        "valid_required_tags": sum(row["status"] == "valid" for row in measured)
        if requested
        else 0,
        "required_tag_deviations": sum(row["status"] != "valid" for row in measured)
        if requested
        else 0,
        "descriptive_marker_status_counts": dict(
            Counter(row["status"] for row in measured)
        ),
        "need_none_responses": len(eligible),
        "need_none_matching_dispatches": sum(
            row["none_action_dispatched"] for row in eligible
        ),
        "need_none_unmatched_dispatches": sum(
            not row["none_action_dispatched"] for row in eligible
        ),
        "incomplete_model_requests": sum(cycle["response"] is None for cycle in cycles),
        "responses": measured,
        "limit": "Observational public task labels only. Dispatch fields mean ManualToolkit tool_request entry before scheduler/argument validation, not proven handler entry or physical execution/success; returned errors, cancellations and missing returns are separate; NEED truth is not inferred. Markers never change official success, classification, retries, or actions.",
    }


def safe_workflow_metrics(events, root, selected_actions):
    """Keep every reporting/parser exception outside task validity classification."""
    requested = None
    try:
        user = Path(root) / "language-materials/user.md"
        if not user.exists():
            return None
        requested = hashlib.sha256(user.read_bytes()).hexdigest() == W2_USER_SHA256
        return analyze_workflow(events, root, selected_actions, requested=requested)
    except Exception as exc:
        return {
            "workflow_requested": requested,
            "metric_error": type(exc).__name__,
            "classification_unchanged": True,
            "limit": "Workflow reporting failed; official task outcome remains authoritative.",
        }
