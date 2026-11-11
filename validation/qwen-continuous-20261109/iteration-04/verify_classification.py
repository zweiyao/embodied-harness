# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Replay the real rejected calls and falsify broader error reclassification."""

import copy
import json
from pathlib import Path

from model_argument_failure import argument_failure_evidence, evidence_from_events
from run_batch import classify

ROOT = Path(__file__).resolve().parent
incident = json.loads((ROOT / "a/incidents.json").read_text())[0]
path = Path(incident["path"])
outcome = json.loads((path / "outcome.json").read_text())
proof = argument_failure_evidence(path, outcome)
assert proof and classify(outcome, run_path=path) == ("model_argument_error", False)
assert classify(outcome) == ("unexpected", None)
events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
requests = [e for e in events if e["kind"] == "model_request"][-2:]
responses = [e for e in events if e["kind"] == "model_response"][-2:]
fixture = []
for request, response in zip(requests, responses):
    request = {
        "kind": "model_request",
        "payload": {
            "model_request_parameters": request["payload"]["model_request_parameters"],
            "messages": [
                {
                    "parts": [
                        p
                        for message in request["payload"]["messages"]
                        for p in message["parts"]
                        if p.get("part_kind") == "retry-prompt"
                    ]
                }
            ],
        },
    }
    fixture.extend([request, response])
manifest = json.loads((path / "manifest.json").read_text())
assert evidence_from_events(fixture, manifest, outcome)
checks = ["actual_episode_reclassified", "no_evidence_remains_unexpected"]

transport = {**outcome, "error": "ConnectionError: connection reset"}
assert evidence_from_events(fixture, manifest, transport) is None
checks.append("transport_error_not_reclassified")

changed = copy.deepcopy(fixture)
call = next(
    p for p in changed[-1]["payload"]["parts"] if p.get("part_kind") == "tool-call"
)
call["args"] = json.dumps({"points": [[0.5, 0.5]], "step": 0, "camera": "agentview"})
assert evidence_from_events(changed, manifest, outcome) is None
checks.append("valid_final_call_not_reclassified")

changed_manifest = copy.deepcopy(manifest)
next(t for t in changed_manifest["tools"] if t["name"] == "sensor_patch_batch")[
    "parameters"
]["properties"]["points"]["maxItems"] = 99
assert evidence_from_events(fixture, changed_manifest, outcome) is None
checks.append("schema_mismatch_not_reclassified")

changed = copy.deepcopy(fixture)
changed[-2]["payload"]["messages"] = []
assert evidence_from_events(changed, manifest, outcome) is None
checks.append("missing_retry_not_reclassified")

changed = copy.deepcopy(fixture)
changed.append(
    {
        "kind": "tool_request",
        "payload": {
            "call_id": "independent_runtime_journal_id",
            "name": "sensor_patch_batch",
        },
    }
)
assert evidence_from_events(changed, manifest, outcome) is None
checks.append("dispatched_call_not_reclassified")

assert classify(
    {"status": "timeout", "error": "planner timed out after 600s", "elapsed_s": 600},
    600,
) == ("budget_timeout", False)
assert classify(
    {"status": "timeout", "error": "planner timed out after 600s", "elapsed_s": 100},
    600,
) == ("unexpected", None)
assert classify(
    {"status": "budget_exhausted", "error": None, "environment_success": False}, 600
) == ("task_result", False)
checks.extend(
    [
        "full_budget_timeout_failure",
        "early_timeout_unexpected",
        "request_budget_failure",
    ]
)
result = {"passed": True, "checks": checks, "actual_evidence": proof}
(ROOT / "classification-checks.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"passed": True, "checks": len(checks)}))
