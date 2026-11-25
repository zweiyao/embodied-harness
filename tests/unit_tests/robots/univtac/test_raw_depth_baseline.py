# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Provider usage is cumulative; unreported fields must remain unknown."""

import json

import pytest

from examples.univtac import raw_depth_baseline
from examples.univtac.raw_depth_baseline import summarize
from rpent.dashboard.workbench import RunJournal


def test_summary_uses_final_cumulative_usage_and_official_success(tmp_path):
    events = [
        {
            "kind": "sdk_event",
            "payload": {
                "method": "thread/tokenUsage/updated",
                "payload": {
                    "token_usage": {"total": {"input_tokens": n, "output_tokens": 20}}
                },
            },
        }
        for n in (100, 250)
    ]
    events.append(
        {"kind": "tool_response", "payload": {"name": "move_eef", "elapsed_s": 1.25}}
    )
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    result = summarize(
        {
            "id": "test",
            "path": str(tmp_path),
            "outcome": {
                "environment_success": False,
                "finish": {"status": "success"},
                "stats": {"total_reasoning_output_tokens": 0},
            },
        }
    )
    assert result["official_success"] is False
    assert result["input_tokens"] == 250
    assert result["reasoning_output_tokens"] is None
    assert result["tool_execution_s"] == 1.25


def test_summary_keeps_missing_usage_unknown(tmp_path):
    (tmp_path / "events.jsonl").write_text("")
    result = summarize({"id": "test", "path": str(tmp_path), "outcome": {}})
    assert result["input_tokens"] is None
    assert result["official_success"] is None


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        (
            [
                {"input_tokens": 60},
                {"input_tokens": 200, "output_tokens": 40},
                {"input_tokens": 60, "cached_input_tokens": 0},
            ],
            (200, 40, None),
        ),
        ([{"input_tokens": 200, "output_tokens": 40}, {}, None], (200, 40, None)),
        (
            [
                {"input_tokens": 200, "output_tokens": 40},
                {"input_tokens": 0, "output_tokens": 0},
            ],
            (200, 40, None),
        ),
        ([{"input_tokens": 0, "output_tokens": 0}], (0, 0, None)),
        (
            [{"input_tokens": 200, "output_tokens": 40}, {"input_tokens": 230}],
            (230, None, None),
        ),
    ],
)
def test_cumulative_usage_ignores_replayed_and_empty_updates(
    tmp_path, updates, expected
):
    events = [
        {
            "kind": "sdk_event",
            "payload": {
                "method": "thread/tokenUsage/updated",
                "payload": {"token_usage": {"total": total}},
            },
        }
        for total in updates
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(map(json.dumps, events)))
    result = summarize({"id": "usage", "path": str(tmp_path), "outcome": {}})
    assert (
        result["input_tokens"],
        result["output_tokens"],
        result["cached_input_tokens"],
    ) == expected


def test_native_startup_failure_survives_without_a_planner_journal(tmp_path):
    result = summarize(
        {
            "id": "startup",
            "path": str(tmp_path),
            "outcome": {
                "termination_reason": "setup_failure",
                "environment_success": None,
                "stats": None,
                "error": "environment initialization failed",
            },
        }
    )
    assert result["termination"] == "setup_failure"
    assert result["official_success"] is None
    assert result["input_tokens"] is None
    assert result["tool_execution_s"] is None
    assert result["tool_calls"] is None


def test_task_summary_retains_verdict_and_termination_independently():
    rows = [
        {"termination": "completed", "official_success": True},
        {"termination": "completed", "official_success": False},
        {"termination": "budget_exhausted", "official_success": False},
        {"termination": "timeout", "official_success": None, "error": "env.reset"},
        {
            "termination": "timeout",
            "official_success": True,
            "error": "planner timeout",
        },
        {"termination": "network_failure", "official_success": False},
        {"termination": "completed", "official_success": None},
        {"official_success": False},
    ]
    result = raw_depth_baseline.summarize_outcomes(rows)
    assert (result["successes"], result["trials"]) == (2, 8)
    assert result["evaluated"] == {"successes": 1, "failures": 2, "trials": 3}
    assert result["other_attempts"] == {
        "timeout": {"official_true": 1, "unreported": 1},
        "network_failure": {"official_false": 1},
        "completed": {"unreported": 1},
        "unreported": {"official_false": 1},
    }


def test_task_summary_requires_a_boolean_and_a_clean_termination():
    result = raw_depth_baseline.summarize_outcomes(
        [
            {"termination": "completed", "official_success": 1},
            {
                "termination": "completed",
                "official_success": True,
                "error": "cleanup failed",
            },
        ]
    )
    assert result["evaluated"] == {"successes": 0, "failures": 0, "trials": 0}
    assert result["other_attempts"]["completed"] == {
        "unreported": 1,
        "official_true": 1,
    }


@pytest.mark.parametrize("reply_received", [True, False])
def test_submission_journal_distinguishes_an_acknowledgement_from_a_lost_reply(
    tmp_path, reply_received
):
    journal = RunJournal(tmp_path)
    path = tmp_path / "events.jsonl"

    def events():
        return [json.loads(line) for line in path.read_text().splitlines()]

    def api(route, message):
        assert [event["kind"] for event in events()] == ["submission_started"]
        assert (route, message) == (
            "/api/session/messages",
            {"text": "/rpent-task univtac 1 4"},
        )
        if not reply_received:
            raise ConnectionError("reply lost")
        return {"ok": True}

    if reply_received:
        raw_depth_baseline.submit_trial(api, journal, 1, 4)
    else:
        with pytest.raises(ConnectionError, match="reply lost"):
            raw_depth_baseline.submit_trial(api, journal, 1, 4)
    log = events()
    assert [e["kind"] for e in log] == (
        ["submission_started", "submission_accepted"]
        if reply_received
        else ["submission_started"]
    )
    assert all(e["payload"] == {"task": 1, "seed": 4} for e in log)


@pytest.mark.parametrize(
    ("session_id", "catalog_id", "cell", "matches"),
    [
        ("current", "current", {"task": 1, "seed": 0}, True),
        ("current", "restored", {"task": 1, "seed": 0}, False),
        ("current", "current", {"task": 2, "seed": 0}, False),
        ("current", "current", {"task": 1, "seed": 37}, False),
        ("current", "current", None, False),
        (None, None, {"task": 1, "seed": 0}, False),
    ],
)
def test_finalized_run_belongs_to_the_session_and_requested_cell(
    session_id, catalog_id, cell, matches
):
    run = {"id": catalog_id, "config": {"task": cell}}
    state = {"run_id": session_id}
    if matches:
        raw_depth_baseline.verify_trial_identity(run, state, 1, 0)
    else:
        with pytest.raises(RuntimeError, match="Unexpected finalized run"):
            raw_depth_baseline.verify_trial_identity(run, state, 1, 0)
