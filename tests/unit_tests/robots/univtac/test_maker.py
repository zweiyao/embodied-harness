# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Controlled maker input/recording tests; no network or candidate execution."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import openai_codex
import pytest
from openai_codex.generated.v2_all import TurnStatus

from robots.univtac.pilot import Pilot
from robots.univtac.pilot import maker as module
from tests.unit_tests.robots.univtac.test_pilot import scene
from tests.unit_tests.robots.univtac.test_replay import sensors  # noqa: F401


@pytest.fixture
def pilot(tmp_path, sensors):  # noqa: F811 - pytest fixture imported above
    pilot = Pilot.create(tmp_path / "pilot")
    actions, feedback = tmp_path / "actions.json", tmp_path / "feedback.json"
    actions.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "state": {"eef_pose_wxyz": [0, 0, 1, 1, 0, 0, 0]},
                        "native_success": True,
                    }
                ]
            }
        )
    )
    feedback.write_text(
        json.dumps(
            {
                "calls": [
                    {
                        "name": "sensor_x",
                        "arguments": {},
                        "result": {"error": "missing frame", "hidden_target": 99},
                    }
                ]
            }
        )
    )
    for cell in pilot.manifest["cells"][:6]:
        attempt = pilot.reserve_episode(cell["id"], cell["id"])
        pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt,
            {
                "termination_reason": "completed",
                "native_success": True,
                "maker_inputs": {
                    "sensors": str(sensors),
                    "actions": str(actions),
                    "feedback": str(feedback),
                },
            },
        )
    return pilot


def answer():
    return json.dumps(
        {
            "name": "sensor_new",
            "description": "A candidate",
            "parameters_json": json.dumps(
                {"type": "object", "properties": {}, "additionalProperties": False}
            ),
            "source": "def run(frames, params): return {}",
        }
    )


def test_branches_share_pixels_and_arrays_only_g1_has_max_feedback(pilot):
    attempts, _, g0, images0, common0 = module.build_inputs(pilot, "G0")
    _, _, g1, images1, common1 = module.build_inputs(pilot, "G1")
    assert common0 == common1 and images0 == images1
    feedback = g1.pop("user_feedback")
    assert g0 == g1 and len(feedback) == 2 and len(attempts) == 4
    # Fixture intentionally lacks wrist/right images: do not invent missing pixels.
    assert len(images0) == 32 and images0[0].startswith(b"\x89PNG")
    first = g0["development"][0]["frames"][0]
    assert first["cameras"]["head"]["depth"]["sample_values"]
    assert first["tactile"]["left"]["marker_reference"]["values"]
    assert first["tactile"]["left"]["marker_current"]["values"][1][0] is None
    assert "rgb" not in first["tactile"]["right"]
    assert [f["step"] for f in g0["development"][0]["frames"]] == [0, 1, 3, 5]
    assert "native_success" not in json.dumps(g0)
    assert "hidden_target" not in json.dumps(feedback)
    assert g0["base_source"] == "def run(frames, params):\n    return {}\n"


def test_incomplete_development_does_not_dispatch_or_charge(tmp_path, monkeypatch):
    pilot = Pilot.create(tmp_path / "pilot")
    monkeypatch.setattr(
        module.codex_sdk, "complete_recorded", lambda *a, **k: pytest.fail("no request")
    )
    with pytest.raises(KeyError):
        module.run(pilot.root, "G0")
    assert pilot.summary()["offline_requests"] == 0


@pytest.mark.parametrize(
    "usage,status",
    [
        ({"total": {"output_tokens": 250}}, "completed"),
        ({}, "failed"),
        ({"total": {"output_tokens": 8193}}, "failed"),
    ],
)
def test_one_request_journals_input_output_usage_and_posthoc_cap(
    pilot, monkeypatch, usage, status
):
    def complete(model, system, payload, images, **options):
        assert model == "gpt-6-astra" and options["timeout_s"] == 180
        assert options["output_schema"] == module.OUTPUT_SCHEMA
        assert pilot.summary()["offline_requests"] == 1
        options["on_event"](
            {"method": "test", "payload": {"access_token": "must redact"}}
        )
        return answer(), usage

    monkeypatch.setattr(module.codex_sdk, "complete_recorded", complete)
    result = module.run(pilot.root, "G0")
    assert result["status"] == status
    assert result["token_limit_mode"] == "soft_limit_and_posthoc_check"
    root = Path(result["artifact_dir"])
    recorded = json.loads((root / "request.json").read_text())
    assert recorded["prompt"] == module.codex_sdk.request_prompt(
        module.SYSTEM, recorded["payload"]
    )
    assert len(list(root.glob("image-*.png"))) == 32
    assert (root / "response.txt").read_text() == answer()
    assert "must redact" not in (root / "events.jsonl").read_text()
    assert (root / "candidate.json").exists() == (status == "completed")
    assert (
        json.loads((pilot.root / "events.jsonl").read_text().splitlines()[-1])["kind"]
        == "offline_result"
    )


def test_timeout_consumes_request_and_keeps_incremental_events(pilot, monkeypatch):
    def complete(*args, **options):
        options["on_event"](
            {"method": "item/agentMessage/delta", "payload": {"delta": "partial"}}
        )
        raise TimeoutError("timed out")

    monkeypatch.setattr(module.codex_sdk, "complete_recorded", complete)
    result = module.run(pilot.root, "G1")
    assert result["status"] == "failed" and "TimeoutError" in result["error"]
    assert "partial" in (Path(result["artifact_dir"]) / "events.jsonl").read_text()
    assert pilot.summary()["offline_requests"] == 1


def test_pair_contract_drift_rejected_before_another_request(pilot, monkeypatch):
    monkeypatch.setattr(
        module.codex_sdk,
        "complete_recorded",
        lambda *a, **k: (answer(), {"total": {"output_tokens": 10}}),
    )
    assert module.run(pilot.root, "G0")["status"] == "completed"
    monkeypatch.setattr(module, "SYSTEM", "changed")
    with pytest.raises(ValueError, match="settings differ"):
        module.run(pilot.root, "G1")
    assert pilot.summary()["offline_requests"] == 1


def test_missing_prior_usage_cannot_claim_verified_branch_budget(pilot, monkeypatch):
    monkeypatch.setattr(
        module.codex_sdk, "complete_recorded", lambda *a, **k: (answer(), {})
    )
    assert module.run(pilot.root, "G0")["status"] == "failed"
    monkeypatch.setattr(
        module.codex_sdk,
        "complete_recorded",
        lambda *a, **k: (answer(), {"total": {"output_tokens": 10}}),
    )
    result = module.run(pilot.root, "G0")
    assert "Prior maker" in result["error"] and result["budget_check"] == "not_passed"
    with pytest.raises(ValueError, match="budget exhausted"):
        module.run(pilot.root, "G0")


@pytest.mark.parametrize("tool,timeout", [(False, False), (True, False), (False, True)])
def test_recorded_sdk_stream_rejects_tools_and_cleans_up(monkeypatch, tool, timeout):
    seen, events = {}, []

    def event(method, **payload):
        value = SimpleNamespace(**payload, model_dump=lambda **_: {"recorded": method})
        return SimpleNamespace(method=method, payload=value)

    class FakeCodex:
        def __init__(self, config):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            seen["closed"] = True

        async def thread_start(self, **options):
            assert (
                options["ephemeral"]
                and options["approval_mode"] == openai_codex.ApprovalMode.deny_all
            )
            return self

        async def turn(self, inputs, **options):
            assert options["output_schema"] == module.OUTPUT_SCHEMA
            return self

        async def interrupt(self):
            seen["interrupted"] = True

        async def stream(self):
            try:
                if timeout:
                    await asyncio.sleep(10)
                yield event(
                    "item/started",
                    item=SimpleNamespace(
                        type="commandExecution" if tool else "agentMessage"
                    ),
                )
                yield event(
                    "item/completed",
                    item=SimpleNamespace(type="agentMessage", text=answer()),
                )
                yield event(
                    "thread/tokenUsage/updated",
                    token_usage=SimpleNamespace(
                        model_dump=lambda **_: {"total": {"output_tokens": 10}}
                    ),
                )
                yield event(
                    "turn/completed",
                    turn=SimpleNamespace(status=TurnStatus.completed, error=None),
                )
            finally:
                seen["stream_closed"] = True

    monkeypatch.setattr(openai_codex, "AsyncCodex", FakeCodex)

    async def call():
        return await asyncio.wait_for(
            module.codex_sdk._complete(
                None,
                "gpt-6-astra",
                "input",
                [],
                output_schema=module.OUTPUT_SCHEMA,
                on_event=events.append,
            ),
            timeout=0.02,
        )

    if tool or timeout:
        with pytest.raises((TimeoutError, RuntimeError)):
            asyncio.run(call())
        assert seen["interrupted"]
    else:
        text, usage = asyncio.run(call())
        assert text == answer() and usage["total"]["output_tokens"] == 10
        assert len(events) == 4
    assert seen["closed"] and seen["stream_closed"]
