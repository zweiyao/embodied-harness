# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Check argument-error classification against real prior evidence and P schemas."""

import copy
import json
from pathlib import Path

from model_argument_failure import argument_failure_evidence, evidence_from_events
from rpent.dashboard.workbench import native_catalog
from run_batch import classify

ROOT = Path(__file__).resolve().parent
prior = json.loads((ROOT.parent / "iteration-04/a/incidents.json").read_text())[0]
outcome = json.loads((Path(prior["path"]) / "outcome.json").read_text())
assert argument_failure_evidence(prior["path"], outcome)
assert classify(outcome, run_path=prior["path"]) == ("model_argument_error", False)
assert classify(outcome) == ("unexpected", None)
tool = next(t for t in native_catalog() if t["name"] == "preview_placement")
valid = {
    "step": 0,
    "camera": "agentview",
    "held_feature": [100, 200],
    "target_region": [[100, 100], [100, 200], [200, 200], [200, 100]],
    "plane_samples": [[100, 100], [100, 200], [200, 200], [200, 100]],
}
bad = [
    {**valid, "held_feature": [0.2, 0.4]},
    {**valid, "held_feature": ["bad", 100, 200]},
]
events = []
for index, args in enumerate(bad):
    request = {
        "model_request_parameters": {
            "function_tools": [
                {"name": tool["name"], "parameters_json_schema": tool["parameters"]}
            ],
            "output_tools": [],
        },
        "messages": []
        if index == 0
        else [
            {
                "parts": [
                    {
                        "part_kind": "retry-prompt",
                        "tool_name": tool["name"],
                        "tool_call_id": "call0",
                        "content": "Invalid arguments for preview_placement: integer pixels required",
                    }
                ]
            }
        ],
    }
    response = {
        "parts": [
            {
                "part_kind": "tool-call",
                "tool_name": tool["name"],
                "args": json.dumps(args),
                "tool_call_id": f"call{index}",
            }
        ]
    }
    events.extend(
        [
            {"kind": "model_request", "payload": request},
            {"kind": "model_response", "payload": response},
        ]
    )
manifest = {"tools": [tool]}
p_outcome = {
    "status": "error",
    "environment_success": False,
    "error": "UnexpectedModelBehavior: Tool 'preview_placement' exceeded max retries count of 1.",
}
assert evidence_from_events(events, manifest, p_outcome)
checks = [
    "real_04_rejected_arguments",
    "missing_run_evidence_unexpected",
    "P_actual_integer_pixel_schema_failure",
]

changed = copy.deepcopy(events)
changed[-1]["payload"]["parts"][0]["args"] = json.dumps(valid)
assert evidence_from_events(changed, manifest, p_outcome) is None
checks.append("valid_P_final_call_unexpected")
changed_manifest = copy.deepcopy(manifest)
changed_manifest["tools"][0]["parameters"]["properties"]["step"]["minimum"] = 999
assert evidence_from_events(events, changed_manifest, p_outcome) is None
checks.append("P_declaration_mismatch_unexpected")
changed = copy.deepcopy(events)
changed[-2]["payload"]["messages"] = []
assert evidence_from_events(changed, manifest, p_outcome) is None
checks.append("P_missing_retry_unexpected")
changed = copy.deepcopy(events)
changed.append(
    {
        "kind": "tool_request",
        "payload": {"name": "preview_placement", "call_id": "runtime_independent_id"},
    }
)
assert evidence_from_events(changed, manifest, p_outcome) is None
checks.append("P_dispatched_implementation_unexpected")
assert evidence_from_events(events, {"tools": []}, p_outcome) is None
checks.append("unselected_tool_unexpected")
assert (
    evidence_from_events(
        events, manifest, {**p_outcome, "error": "ConnectionError: reset"}
    )
    is None
)
checks.append("network_error_unexpected")
assert classify(
    {"status": "timeout", "error": "planner timed out after 600s", "elapsed_s": 600}
) == ("budget_timeout", False)
assert classify(
    {"status": "timeout", "error": "planner timed out after 600s", "elapsed_s": 20}
) == ("unexpected", None)
checks.extend(["full_budget_timeout_failure", "early_timeout_unexpected"])
result = {
    "passed": True,
    "checks": checks,
    "P_schema_version": tool["version"],
    "model_requests": 0,
    "simulator_actions": 0,
}
(ROOT / "classification-checks.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
