# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Exercise finish-only journal accounting; no SDK, model or simulator calls."""

import json
import tempfile
from pathlib import Path

from finish_metrics import analyze_finish, safe_finish_metrics
from metrics import analyze

ROOT = Path(__file__).resolve().parent


def request(gate, parts=None):
    return {
        "kind": "model_request",
        "payload": {
            "model_request_parameters": {"allow_text_output": gate},
            "messages": [{"parts": parts or []}],
        },
    }


def response(*parts):
    return {"kind": "model_response", "payload": {"parts": list(parts)}}


text = {"part_kind": "text", "content": "NEXT=pi0_pick; NEED=none"}
finish = {
    "part_kind": "tool-call",
    "tool_name": "finish",
    "args": "{}",
    "tool_call_id": "provider-finish",
}
move = {
    "part_kind": "tool-call",
    "tool_name": "translate_to",
    "args": "{}",
    "tool_call_id": "provider-move",
}
retry = {
    "part_kind": "retry-prompt",
    "tool_name": None,
    "content": "Recorded output-validation feedback fixture",
}
checks = []
result = analyze_finish([request(True), response(text)])
assert result["actual_allow_text_output_counts"] == {"True": 1}
assert result["last_pure_text_without_followup_request"] == 1
assert result["finish_model_attempts"] == result["finish_toolkit_entries"] == 0
checks.append("default_text_completion_is_not_a_finish_or_action")
events = [
    request(False),
    response(text),
    request(False, [retry]),
    response(move),
    request(False, [retry]),
]
result = analyze_finish(events)
assert result["actual_allow_text_output_counts"] == {"False": 3}
assert len(result["pure_text_followed_by_output_retry"]) == 1
assert result["pure_text_followed_by_output_retry"][0]["rejected_response_request"] == 1
assert result["last_pure_text_without_followup_request"] is None
checks.append("pure_text_retry_association_not_recounted_from_history")
result = analyze_finish([request(False), response(text, move)])
assert result["completed_response_kinds"] == {"mixed_text_and_tool_calls": 1}
assert result["last_pure_text_without_followup_request"] is None
checks.append("mixed_text_and_tool_call_is_not_pure_text_rejection")
result = analyze_finish([request(False), response(finish)])
assert result["finish_model_attempts"] == 1 and result["finish_toolkit_entries"] == 0
checks.append("attempted_finish_without_toolkit_entry_not_accepted")
entered = {
    "kind": "tool_request",
    "payload": {"name": "finish", "call_id": "runtime-finish", "arguments": {}},
}
accepted = {
    "kind": "tool_response",
    "payload": {
        "name": "finish",
        "call_id": "runtime-finish",
        "result": {"_finish": True},
    },
}
result = analyze_finish([request(False), response(finish), entered, accepted])
assert result["accepted_finish_returns"] == 1 and "official_success" not in result
checks.append("accepted_finish_flag_does_not_infer_official_success")
rejected = {
    "kind": "tool_response",
    "payload": {
        "name": "finish",
        "call_id": "runtime-finish",
        "result": {"error": "goal remains false"},
    },
}
result = analyze_finish([request(False), response(finish), entered, rejected])
assert result["finish_toolkit_entries"] == 1 and result["accepted_finish_returns"] == 0
assert result["finish_returns"][0]["return_error"]
checks.append("rejected_finish_return_stays_separate")
result = analyze_finish([request(False), response(finish), entered])
assert (
    not result["finish_returns"][0]["returned"]
    and result["accepted_finish_returns"] == 0
)
checks.append("missing_finish_return_not_accepted")
other_retry = {**retry, "tool_name": "translate_to"}
result = analyze_finish([request(False), response(text), request(False, [other_retry])])
assert not result["pure_text_followed_by_output_retry"]
checks.append("named_tool_retry_not_counted_as_pure_text_output_retry")
result = safe_finish_metrics(
    [request(False), {"kind": "model_response", "payload": {"parts": None}}]
)
assert result == {"metric_error": "TypeError", "classification_unchanged": True}
checks.append("reporter_error_cannot_become_an_experiment_incident")
with tempfile.TemporaryDirectory(prefix="rpent-finish-metrics-") as directory:
    events = [request(False), {"kind": "model_response", "payload": {"parts": None}}]
    for index, event in enumerate(events):
        event["time"] = f"2026-11-10T00:00:0{index}+00:00"
    (Path(directory) / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events)
    )
    result = analyze(directory)
    assert result["finish_only"]["metric_error"] == "TypeError"
    assert result["completed_model_responses"] == 1 and result["memory_audit_passed"]
    assert result["all_calls"] == 0 and result["completed_model_wait_sum_s"] == 1
checks.append("integrated_finish_metric_error_preserves_core_metrics")
report = {
    "passed": True,
    "checks": checks,
    "model_requests": 0,
    "simulator_actions": 0,
    "scope": "Observational journal parser only; SDK enforcement is verified separately by F source validation.",
}
(ROOT / "finish-metric-checks.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
