# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Reject false phase transitions and mismatched actual API exposure."""

import copy

import pytest
from phase_audit import audit_phase

FULL = [
    {"name": n, "description": "fixture"}
    for n in ("pi0_pick", "translate_to", "finish")
]
INITIAL = [t for t in FULL if t["name"] != "translate_to"]


def request(tools):
    return {
        "kind": "model_request",
        "payload": {
            "model_request_parameters": {
                "function_tools": tools[:-1],
                "output_tools": tools[-1:],
            }
        },
    }


@pytest.fixture
def evidence():
    events = [
        request(INITIAL),
        {"kind": "tool_request", "payload": {"name": "pi0_pick", "call_id": "p"}},
        {
            "kind": "workflow_phase",
            "payload": {
                "phase": "manual_available",
                "trigger": "pi0_pick",
                "after_step": 1,
            },
        },
        {
            "kind": "tool_response",
            "payload": {"name": "pi0_pick", "call_id": "p", "result": {"step": 1}},
        },
        request(FULL),
    ]
    states = [
        {
            "step_idx": 1,
            "command": {"action": "pi0_pick"},
            "result": {"chunks_used": 2, "success": False},
        }
    ]
    return events, states


def test_failed_pickup_unlocks_without_success_inference(evidence):
    events, states = evidence
    result = audit_phase(events, states, FULL)
    assert result["passed"] and result["transition"]["chunks_used"] == 2
    assert "success" not in result


def test_no_action_finish_or_timeout_needs_no_transition():
    result = audit_phase([request(INITIAL)], [], FULL)
    assert result["passed"] and result["transition"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "early_tools",
        "late_tools",
        "schema",
        "zero_chunks",
        "wrong_action",
        "missing_marker",
        "repeat_marker",
        "early_dispatch",
    ],
)
def test_invalid_phase_evidence_is_rejected(evidence, fault):
    events, states = copy.deepcopy(evidence)
    if fault == "early_tools":
        events[0] = request(FULL)
    elif fault == "late_tools":
        events[-1] = request(INITIAL)
    elif fault == "schema":
        events[-1]["payload"]["model_request_parameters"]["function_tools"][0][
            "description"
        ] = "wrong"
    elif fault == "zero_chunks":
        states[0]["result"]["chunks_used"] = 0
    elif fault == "wrong_action":
        states[0]["command"]["action"] = "view_env_state"
    elif fault == "missing_marker":
        events.pop(2)
    elif fault == "repeat_marker":
        events.insert(3, copy.deepcopy(events[2]))
    elif fault == "early_dispatch":
        events[1]["payload"]["name"] = "translate_to"
    with pytest.raises(AssertionError):
        audit_phase(events, states, FULL)
