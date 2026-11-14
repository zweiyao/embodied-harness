# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from rpent.evaluation.decision_summary import (
    DecisionSummary,
    action_packets,
    summarize_run,
    summary_schema,
    validate_summary,
)


def journal(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "tools": [
                    {"name": "move_to", "category": "control"},
                    {"name": "finish", "category": "control"},
                ]
            }
        )
    )
    (run / "outcome.json").write_text(json.dumps({"environment_success": False}))
    records = [
        (
            "tool_response",
            {
                "call_id": "obs",
                "name": "view_env_state",
                "result": {"visible": "blocked"},
            },
        ),
        (
            "sdk_event",
            {
                "method": "item/completed",
                "payload": {
                    "item": {
                        "type": "agentMessage",
                        "text": "The grasp failed. I will withdraw.",
                    }
                },
            },
        ),
        (
            "tool_request",
            {"call_id": "action-a", "name": "move_to", "arguments": {"xyz": [0, 0, 0]}},
        ),
        (
            "tool_request",
            {"call_id": "parallel-obs", "name": "view_env_state", "arguments": {}},
        ),
        (
            "tool_response",
            {
                "call_id": "parallel-obs",
                "name": "view_env_state",
                "result": {"future": "not decision evidence"},
            },
        ),
        (
            "tool_response",
            {"call_id": "action-a", "name": "move_to", "result": {"reached": True}},
        ),
        ("tool_request", {"call_id": "finish", "name": "finish", "arguments": {}}),
    ]
    (run / "events.jsonl").write_text(
        "\n".join(
            json.dumps({"time": str(i), "kind": kind, "payload": payload})
            for i, (kind, payload) in enumerate(records)
        )
    )
    return run


def summary(**updates):
    return DecisionSummary.model_validate(
        {
            "observations": [],
            "model_statements": [],
            "explicit_choice_basis": [],
            "reviewer_inferences": [],
            "unknowns": ["Internal reasoning unavailable"],
            **updates,
        }
    )


def test_action_prefix_excludes_future_and_pairs_concurrent_feedback(tmp_path):
    (packet,) = action_packets(journal(tmp_path))
    assert [e["id"] for e in packet["before"]] == ["E1", "E2"]
    assert packet["after"]["id"] == "E6"
    assert packet["after"]["result"] == {"reached": True}


def test_api_visible_text_is_separate_from_thinking_parts(tmp_path):
    run = journal(tmp_path)
    path = run / "events.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    rows[1] = {
        "time": "1",
        "kind": "model_response",
        "payload": {
            "parts": [
                {"part_kind": "text", "content": "The grasp failed; I will withdraw."},
                {"part_kind": "thinking", "content": "not a visible statement"},
            ]
        },
    }
    path.write_text("\n".join(json.dumps(x) for x in rows))
    (packet,) = action_packets(run)
    assert packet["before"][-1]["kind"] == "model_text"
    assert "not a visible statement" not in packet["before"][-1]["text"]


def test_images_are_from_completed_observation_before_action_not_later_feedback(
    tmp_path,
):
    run = journal(tmp_path)
    path = run / "events.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    rows[0]["payload"]["images"] = [{"artifact": "inputs/before.bin", "bytes": 10}]
    rows[5]["payload"]["images"] = [{"artifact": "inputs/after.bin", "bytes": 20}]
    path.write_text("\n".join(json.dumps(x) for x in rows))
    (packet,) = action_packets(run)
    assert packet["images"] == [
        {"id": "E1", "artifact": "inputs/before.bin", "bytes": 10}
    ]


@pytest.mark.parametrize(
    "field,reference",
    [
        ("observations", "E6"),
        ("reviewer_inferences", "invented"),
        ("explicit_choice_basis", "E1"),
        ("model_statements", "E1"),
    ],
)
def test_rejects_future_or_invented_evidence_and_false_attribution(
    tmp_path, field, reference
):
    (packet,) = action_packets(journal(tmp_path))
    with pytest.raises(ValueError):
        validate_summary(
            summary(**{field: [{"text": "unsupported", "evidence": [reference]}]}),
            packet,
        )


def test_only_finalized_runs_are_reviewed(tmp_path):
    run = journal(tmp_path)
    (run / "outcome.json").unlink()
    with pytest.raises(ValueError, match="finalized"):
        action_packets(run)


def test_report_preserves_source_and_reuses_existing_action_without_model_call(
    tmp_path, monkeypatch
):
    run = journal(tmp_path)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir()}
    calls = []

    def review(run_dir, packet, model, timeout_s):
        calls.append(packet["action"]["call_id"])
        assert packet["before"][-1]["id"] == "E2"
        return summary(
            explicit_choice_basis=[
                {"text": "Withdraw after failed grasp", "evidence": ["E2"]}
            ]
        ), {"input_tokens": 11, "output_tokens": 3}

    monkeypatch.setattr("rpent.evaluation.decision_summary_codex.review_action", review)
    output = tmp_path / "analysis"
    report = summarize_run(run, output, "reviewer")
    summarize_run(run, output, "reviewer")
    assert calls == ["action-a"]
    assert before == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir()
    }
    saved = json.loads(report.read_text())
    assert saved["environment_outcome"]["environment_success"] is False
    assert saved["actions"][0]["reviewer_usage"]["input_tokens"] == 11
    assert (output / "decision-summary.md").exists()
    with pytest.raises(ValueError, match="different source"):
        summarize_run(run, output, "different-reviewer")


def test_rejects_foreign_image_before_any_model_access(tmp_path):
    from rpent.evaluation.decision_summary_codex import review_action

    run = journal(tmp_path)
    (packet,) = action_packets(run)
    packet["images"] = [{"id": "E1", "artifact": "../secret.png"}]
    with pytest.raises(ValueError, match="outside"):
        review_action(run, packet, "unused", 1)


@pytest.mark.parametrize("attempt_tool", [False, True])
def test_sdk_request_contract_usage_and_tool_rejection(monkeypatch, attempt_tool):
    import openai_codex

    from rpent.evaluation.decision_summary_codex import _review

    closed = []

    def event(method, payload):
        return SimpleNamespace(
            method=method, payload=SimpleNamespace(model_dump=lambda **kwargs: payload)
        )

    class Turn:
        async def stream(self):
            if attempt_tool:
                yield event("item/completed", {"item": {"type": "mcpToolCall"}})
            yield event(
                "thread/tokenUsage/updated",
                {
                    "token_usage": {
                        "total": {
                            "input_tokens": 12,
                            "output_tokens": 4,
                            "cached_input_tokens": 8,
                        }
                    }
                },
            )
            yield event(
                "item/completed",
                {"item": {"type": "agentMessage", "text": "structured answer"}},
            )
            yield event("turn/completed", {"turn": {"status": "completed"}})

    class Thread:
        async def turn(self, inputs, **options):
            assert inputs == ["evidence only"]
            assert options["effort"] == "low"
            assert "output_schema" in options
            return Turn()

    class Client:
        def __init__(self, config):
            pass

        async def thread_start(self, *, model, approval_mode, sandbox, cwd):
            assert model == "reviewer"
            assert sandbox == openai_codex.Sandbox.read_only
            assert approval_mode == openai_codex.ApprovalMode.deny_all
            assert cwd == "/review"
            return Thread()

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(openai_codex, "AsyncCodex", Client)
    if attempt_tool:
        with pytest.raises(RuntimeError, match="use a tool"):
            asyncio.run(
                _review(
                    SimpleNamespace(cwd="/review"), ["evidence only"], "reviewer", {}
                )
            )
    else:
        answer, usage = asyncio.run(
            _review(SimpleNamespace(cwd="/review"), ["evidence only"], "reviewer", {})
        )
        assert answer == "structured answer"
        assert usage == {
            "input_tokens": 12,
            "output_tokens": 4,
            "cached_input_tokens": 8,
        }
    assert closed == [True]


def test_output_schema_prevents_future_citations_and_wrong_attribution(tmp_path):
    import jsonschema

    (packet,) = action_packets(journal(tmp_path))
    schema = summary_schema(packet)
    jsonschema.validate(summary().model_dump(), schema)
    for field, reference in [("observations", "E6"), ("explicit_choice_basis", "E1")]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                summary(
                    **{field: [{"text": "unsupported", "evidence": [reference]}]}
                ).model_dump(),
                schema,
            )
