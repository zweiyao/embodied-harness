# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Offline protocol tests; no simulator, API or generated code is executed."""

import json
from collections import Counter

import pytest

from robots.univtac.pilot import Pilot, default_manifest


def scene(offset=0):
    return {
        "model": {"revision": "test"},
        "state": {"pose": [offset, 0, 0]},
        "physics": {"dt": 0.01},
        "sensors": {"resolution": [4, 4]},
        "rng": {"state": "fixed"},
        "assets": {"mesh": "hash"},
    }


def development(pilot, tmp_path):
    inputs = {}
    for name in ("sensors", "actions", "feedback"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({name: ["sanitized"]}))
        inputs[name] = str(path)
    attempts = []
    for cell in pilot.manifest["cells"][:6]:
        attempt = pilot.reserve_episode(cell["id"], cell["id"])
        pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt,
            {
                "termination_reason": "completed",
                "native_success": False,
                "maker_inputs": inputs,
            },
        )
        if cell["stage"] != "smoke":
            attempts.append(attempt)
    return attempts


def bundle(attempts, pilot):
    native = {
        "name": "base",
        "description": "base",
        "parameters": {},
        "source": "def base(): pass",
    }
    generated = {
        "name": "sensor_new",
        "description": "measure",
        "parameters": {},
        "source": "def run(frames, params): return {}",
    }
    conditions = {
        name: {
            "tools": [native] + ([generated] if name in "DE" else []),
            "guidance": name,
            "parameters": {},
        }
        for name in "CDEF"
    }
    budget = {"max_calls": 3, "max_tokens": 8192}
    for variant in ("G0", "G1"):
        request = pilot.reserve_offline(
            "maker", variant, attempts, maker_budget=budget, max_tokens=4096
        )
        pilot.finish_offline(request, {"status": "completed", "output_tokens": 10})
    return {
        "conditions": conditions,
        "controller": {"revision": "fixed"},
        "models": {"max_turns": 25},
        "memory": {},
        "code_revision": "test",
        "base_tool": generated,
        "maker_budget": budget,
        "maker_input_attempts": attempts,
        "validation_evidence": {"replay": "development-only"},
    }


def finish_validation(pilot, version):
    for cell in pilot.manifest["cells"][6:8]:
        attempt = pilot.reserve_episode(cell["id"], cell["id"], version)
        pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt,
            {
                "termination_reason": "completed",
                "native_success": False,
                "interface_validation_passed": True,
            },
        )


def test_fixed_budget_and_disjoint_tasks():
    manifest = default_manifest()
    cells = manifest["cells"]
    assert len(cells) == len({cell["id"] for cell in cells}) == 40
    assert {c["task"] for c in cells[:8]} == {"insert_hole"}
    assert {c["task"] for c in cells[8:]} == {"insert_tube", "pull_out_key"}
    assert Counter(c["model"] for c in cells[8:]) == {
        "qwen3.8-max": 24,
        "gpt-6-astra": 8,
    }


def test_failed_start_is_charged_and_cannot_reuse_cell_or_session(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    attempt = pilot.reserve_episode("dev-01", "session")
    reopened = Pilot(pilot.root)
    assert reopened.summary()["episodes_reserved"] == 1
    with pytest.raises(ValueError, match="active"):
        pilot.reserve_episode("dev-02", "session-2")
    pilot.finish_episode(attempt, {"termination_reason": "setup_failure"})
    with pytest.raises(ValueError, match="already"):
        pilot.reserve_episode("dev-01", "new-session")
    with pytest.raises(ValueError, match="already"):
        pilot.reserve_episode("dev-02", "session")
    assert pilot.summary()["termination_counts"] == {"setup_failure": 1}


def test_freeze_and_development_gate_prevent_formal_early_start(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    formal = pilot.manifest["cells"][8]["id"]
    with pytest.raises(ValueError, match="frozen"):
        pilot.reserve_episode(formal, "formal")
    attempts = development(pilot, tmp_path)
    frozen = bundle(attempts, pilot)
    version = pilot.freeze(frozen)
    with pytest.raises(ValueError, match="eight development"):
        pilot.reserve_episode(formal, "formal", version)
    finish_validation(pilot, version)
    pilot.reserve_episode(formal, "formal", version)
    with pytest.raises(ValueError, match="already frozen"):
        pilot.freeze(frozen)


def test_maker_inputs_exclude_evaluator_fields_and_g0_feedback(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    attempts = development(pilot, tmp_path)
    g0 = pilot.maker_inputs("G0", attempts)
    g1 = pilot.maker_inputs("G1", attempts)
    assert all(set(row["files"]) == {"sensors", "actions"} for row in g0)
    assert set(g1[-1]["files"]) == {"sensors", "actions", "feedback"}
    assert "native_success" not in json.dumps(g1)
    path = tmp_path / "sensors.json"
    path.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        pilot.maker_inputs("G1", attempts)


def test_pair_scene_mismatch_is_rejected_without_refunding_attempt(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    version = pilot.freeze(bundle(development(pilot, tmp_path), pilot))
    finish_validation(pilot, version)
    cells = pilot.manifest["cells"][8:10]
    first = pilot.reserve_episode(cells[0]["id"], "first", version)
    pilot.record_scene(first, scene())
    pilot.finish_episode(
        first, {"termination_reason": "completed", "native_success": True}
    )
    second = pilot.reserve_episode(cells[1]["id"], "second", version)
    with pytest.raises(ValueError, match="scene mismatch"):
        pilot.record_scene(second, scene(offset=1))
    pilot.finish_episode(second, {"termination_reason": "scene_mismatch"})
    with pytest.raises(ValueError, match="maker inputs"):
        pilot.maker_inputs("G1", [first])
    assert pilot.summary()["episodes_reserved"] == 10


def test_tampered_frozen_tool_source_is_rejected(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    version = pilot.freeze(bundle(development(pilot, tmp_path), pilot))
    path = pilot.root / f"freeze-{version}.json"
    data = json.loads(path.read_text())
    data["conditions"]["E"]["tools"][-1]["source"] = "tampered"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash mismatch"):
        pilot.reserve_episode("dev-07", "new-session", version)


def test_offline_retries_are_counted_and_capped(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    attempts = development(pilot, tmp_path)
    for _ in range(80):
        pilot.reserve_offline("diagnostic", "G0", attempts)
    with pytest.raises(ValueError, match="budget exhausted"):
        pilot.reserve_offline("diagnostic", "G0", attempts)
    assert pilot.summary()["offline_requests"] == 80


def test_maker_budgets_are_shared_and_failed_requests_not_refunded(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    attempts = development(pilot, tmp_path)
    budget = {"max_calls": 1, "max_tokens": 100}
    request = pilot.reserve_offline(
        "maker", "G0", attempts, maker_budget=budget, max_tokens=100
    )
    pilot.finish_offline(request, {"error": "network failure"})
    with pytest.raises(ValueError, match="branch budget exhausted"):
        pilot.reserve_offline(
            "maker", "G0", attempts, maker_budget=budget, max_tokens=1
        )
    with pytest.raises(ValueError, match="same maker budget"):
        pilot.reserve_offline(
            "maker",
            "G1",
            attempts,
            maker_budget={"max_calls": 2, "max_tokens": 100},
            max_tokens=100,
        )
    pilot.reserve_offline("maker", "G1", attempts, maker_budget=budget, max_tokens=100)


def test_failed_final_validation_blocks_holdout(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    version = pilot.freeze(bundle(development(pilot, tmp_path), pilot))
    for cell in pilot.manifest["cells"][6:8]:
        attempt = pilot.reserve_episode(cell["id"], cell["id"], version)
        pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt,
            {
                "termination_reason": "completed",
                "native_success": False,
                "interface_validation_passed": cell["id"] == "dev-08",
            },
        )
    with pytest.raises(ValueError, match="validations must pass"):
        pilot.reserve_episode(pilot.manifest["cells"][8]["id"], "heldout", version)
