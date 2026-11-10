# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Recognize recorded schema-retry exhaustion, without relabeling other errors."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ERROR_PREFIX = "UnexpectedModelBehavior: Tool 'sensor_patch_batch' exceeded max retries count of 1."


def evidence_from_events(events, manifest, outcome):
    if (
        outcome.get("status") != "error"
        or not str(outcome.get("error", "")).startswith(ERROR_PREFIX)
        or outcome.get("environment_success") is not False
    ):
        return None
    requests = [e["payload"] for e in events if e["kind"] == "model_request"]
    responses = [e["payload"] for e in events if e["kind"] == "model_response"]
    if len(requests) != len(responses) or len(responses) < 2:
        return None
    published = next(
        (t for t in manifest["tools"] if t["name"] == "sensor_patch_batch"), None
    )
    if published is None:
        return None
    first_rejected_event = [
        i for i, e in enumerate(events) if e["kind"] == "model_response"
    ][-2]
    if any(
        e["kind"] == "tool_request" and e["payload"].get("name") == published["name"]
        for e in events[first_rejected_event + 1 :]
    ):
        # Runtime journal call IDs are distinct from provider tool_call_ids.
        return None
    rejected = []
    for index in range(len(responses) - 2, len(responses)):
        tools = requests[index]["model_request_parameters"]["function_tools"]
        declaration = next((t for t in tools if t["name"] == published["name"]), None)
        if (
            declaration is None
            or declaration["parameters_json_schema"] != published["parameters"]
        ):
            return None
        calls = [
            p for p in responses[index]["parts"] if p.get("part_kind") == "tool-call"
        ]
        if len(calls) != 1 or calls[0].get("tool_name") != published["name"]:
            return None
        call = calls[0]
        try:
            arguments = (
                json.loads(call["args"])
                if isinstance(call["args"], str)
                else call["args"]
            )
        except (TypeError, ValueError):
            return None
        errors = list(
            Draft202012Validator(published["parameters"]).iter_errors(arguments)
        )
        if not errors:
            return None
        rejected.append(
            {
                "model_request": index + 1,
                "tool_call_id": call["tool_call_id"],
                "validation_errors": [
                    {"path": list(e.absolute_path), "validator": e.validator}
                    for e in errors
                ],
            }
        )
    retry = [
        p
        for message in requests[-1]["messages"]
        for p in message["parts"]
        if p.get("part_kind") == "retry-prompt"
        and p.get("tool_name") == published["name"]
        and p.get("tool_call_id") == rejected[0]["tool_call_id"]
        and str(p.get("content", "")).startswith(
            "Invalid arguments for sensor_patch_batch:"
        )
    ]
    if not retry:
        return None
    return {
        "tool": published["name"],
        "actual_schema_matches_published": True,
        "rejected_model_calls": rejected,
        "retry_feedback_present": True,
        "rejected_calls_dispatched": False,
        "classification": "model_argument_error",
        "evaluation_success": False,
    }


def argument_failure_evidence(path, outcome):
    root = Path(path)
    events = [
        json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()
    ]
    manifest = json.loads((root / "manifest.json").read_text())
    return evidence_from_events(events, manifest, outcome)
