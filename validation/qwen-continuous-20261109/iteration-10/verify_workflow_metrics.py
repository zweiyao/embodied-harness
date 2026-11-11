# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Independent journal scenarios for observational W2 accounting, without models."""

import json
import tempfile
from pathlib import Path

from metrics import analyze
from workflow_metrics import analyze_workflow, safe_workflow_metrics

ROOT = Path(__file__).resolve().parent
checks = []
with tempfile.TemporaryDirectory(prefix="rpent-w2-metrics-") as directory:
    run = Path(directory)
    (run / "language-materials/memory").mkdir(parents=True)
    guide = run / "language-materials/guide.md"
    index = run / "language-materials/memory/MEMORY.md"
    guide.write_text("frozen guide\n")
    index.write_text("frozen index\n")
    required = [
        ("view_env_state", {"step": 0}, {"step": 0}),
        (
            "read_text_file",
            {"path": str(guide)},
            {"path": str(guide), "content": guide.read_text()},
        ),
        (
            "read_text_file",
            {"path": str(index)},
            {"path": str(index), "content": index.read_text()},
        ),
    ]
    actions = {"pi0_pick", "translate_to", "rotate_axis", "finish"}

    def cycle(number, text, attempts, dispatches):
        parts = [{"part_kind": "text", "content": text}] if text is not None else []
        parts += [
            {
                "part_kind": "tool-call",
                "tool_name": name,
                "args": json.dumps(args),
                "tool_call_id": f"provider-{number}-{i}",
            }
            for i, (name, args, _) in enumerate(attempts)
        ]
        events = [
            {"kind": "model_request", "payload": {}},
            {"kind": "model_response", "payload": {"parts": parts}},
        ]
        for i, (name, args, result) in enumerate(dispatches):
            call_id = f"runtime-{number}-{i}"
            events.extend(
                [
                    {
                        "kind": "tool_request",
                        "payload": {
                            "name": name,
                            "arguments": args,
                            "call_id": call_id,
                        },
                    },
                    {
                        "kind": "tool_response",
                        "payload": {"name": name, "result": result, "call_id": call_id},
                    },
                ]
            )
        return events

    def measure(events, requested=True):
        return analyze_workflow(events, run, actions, requested=requested)

    bootstrap = cycle(1, None, required, required)
    m = measure(bootstrap)
    assert (
        m["bootstrap"]["grouped_success_without_action"]
        and m["required_tag_responses"] == 0
    )
    checks.append("successful_three_call_bootstrap_no_required_tag")
    split = cycle(1, None, required[:1], required[:1]) + cycle(
        2, None, required[1:], required[1:]
    )
    assert not measure(split)["bootstrap"]["three_succeeded_together"]
    checks.append("split_calls_not_batched_startup")
    m = measure(cycle(1, None, required, []))["bootstrap"]
    assert (
        m["three_attempted_together"]
        and not m["three_dispatched_together"]
        and not m["three_succeeded_together"]
    )
    checks.append("attempted_but_not_dispatched")
    failed = [
        required[0],
        (required[1][0], required[1][1], {"error": "denied"}),
        required[2],
    ]
    assert not measure(cycle(1, None, required, failed))["bootstrap"][
        "three_succeeded_together"
    ]
    checks.append("failed_guide_return_not_success")
    wrong = [
        required[0],
        (
            "read_text_file",
            {"path": str(run / "other.md")},
            {"path": str(run / "other.md"), "content": guide.read_text()},
        ),
        required[2],
    ]
    assert not measure(cycle(1, None, wrong, wrong))["bootstrap"][
        "three_succeeded_together"
    ]
    checks.append("wrong_path_same_contents_not_frozen_guide")
    wrong_step = [("view_env_state", {"step": 1}, {"step": 1}), *required[1:]]
    assert not measure(cycle(1, None, wrong_step, wrong_step))["bootstrap"][
        "three_succeeded_together"
    ]
    checks.append("noninitial_view_not_successful_bootstrap")
    pick = ("pi0_pick", {"prompt": "pick target"}, {"step": 1})
    m = measure(cycle(1, None, required + [pick], required + [pick]))["bootstrap"]
    assert (
        m["three_succeeded_together"]
        and m["extra_action_dispatches"] == ["pi0_pick"]
        and not m["grouped_success_without_action"]
    )
    checks.append("extra_bootstrap_action_reported")
    move = ("translate_to", {"xyz": [0, 0, 0]}, {"step": 1})
    follow = cycle(2, "NEXT=translate_to; NEED=none", [move], [move])
    m = measure(bootstrap + follow)
    assert m["valid_required_tags"] == 1 and m["need_none_matching_dispatches"] == 1
    checks.append("valid_action_label_matches_runtime_dispatch")
    m = measure(bootstrap + cycle(2, "NEXT=translate_to; NEED=none", [move], []))
    assert (
        m["responses"][0]["none_action_attempted"]
        and not m["responses"][0]["none_action_dispatched"]
    )
    checks.append("model_action_attempt_not_runtime_dispatch")
    rotate = ("rotate_axis", {"axis": "x", "angle_rad": 0.1}, {"step": 1})
    assert (
        measure(
            bootstrap + cycle(2, "NEXT=translate_to; NEED=none", [rotate], [rotate])
        )["need_none_unmatched_dispatches"]
        == 1
    )
    checks.append("different_action_is_mismatch")
    m = measure(
        bootstrap
        + cycle(2, "NEXT=view_env_state; NEED=none", required[:1], required[:1])
    )
    assert m["required_tag_deviations"] == 1 and m["need_none_responses"] == 0
    checks.append("enabled_readonly_tool_not_enabled_NEXT_action")
    m = measure(
        bootstrap
        + cycle(2, "NEXT=pi0_pick; NEED=target not visible", required[:1], required[:1])
    )
    assert (
        m["valid_required_tags"] == 1
        and m["need_none_responses"] == 0
        and m["responses"][0]["need_semantics"] == "not_mechanically_verified"
    )
    checks.append("nonempty_precondition_recorded_without_truth_inference")
    missing = (
        bootstrap
        + cycle(2, "Inspect next.", [], [])
        + cycle(3, "NEXT=translate_to", [], [])
    )
    assert measure(missing)["required_tag_deviations"] == 2
    m = measure(missing, requested=False)
    assert (
        m["required_tag_responses"] == 0
        and m["required_tag_deviations"] == 0
        and m["descriptive_marker_status_counts"] == {"missing": 1, "malformed": 1}
    )
    checks.append("missing_malformed_labels_observational_parent_not_required")
    finish = ("finish", {"status": "stuck", "summary": "done"}, {"_finish": True})
    assert (
        measure(bootstrap + cycle(2, "NEXT=finish; NEED=NONE", [finish], [finish]))[
            "need_none_matching_dispatches"
        ]
        == 1
    )
    checks.append("finish_uses_actual_journal_dispatch")
    m = measure(bootstrap + follow + [{"kind": "model_request", "payload": {}}])
    assert m["required_tag_responses"] == 1 and m["incomplete_model_requests"] == 1
    checks.append("canceled_request_not_completed_tag_denominator")
    for error_result, expected_status in [
        ({"error": "invalid xyz", "code": "bad_arguments"}, "error"),
        ({"error": "stopped", "code": "tool_cancelled"}, "cancelled"),
    ]:
        rejected_move = (move[0], move[1], error_result)
        m = measure(
            bootstrap
            + cycle(2, "NEXT=translate_to; NEED=none", [move], [rejected_move])
        )
        assert m["responses"][0]["none_action_dispatched"]
        assert (
            m["responses"][0]["action_returns"][0]["return_status"] == expected_status
        )
    checks.append(
        "toolkit_entry_error_and_cancellation_not_handler_or_physical_execution"
    )
    (run / "language-materials/user.md").write_text("fixture")
    m = safe_workflow_metrics([{"kind": "malformed-event"}], run, actions)
    assert m["metric_error"] == "KeyError" and m["classification_unchanged"]
    checks.append("workflow_parser_exception_is_observational_not_incident")
    integrated_events = [
        {"kind": "model_request", "time": "2026-11-10T00:00:00+00:00", "payload": {}},
        {
            "kind": "model_response",
            "time": "2026-11-10T00:00:01+00:00",
            "payload": {"parts": None},
        },
    ]
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in integrated_events)
    )
    m = analyze(run)
    assert m["workflow"]["metric_error"] == "TypeError"
    assert m["workflow"]["classification_unchanged"]
    assert m["completed_model_responses"] == 1 and m["memory_audit_passed"]
    assert m["all_calls"] == 0 and m["completed_model_wait_sum_s"] == 1
    checks.append("integrated_workflow_only_error_preserves_core_analysis")
result = {
    "passed": True,
    "checks": checks,
    "model_requests": 0,
    "simulator_actions": 0,
    "classification_modified": False,
}
(ROOT / "workflow-metric-checks.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
