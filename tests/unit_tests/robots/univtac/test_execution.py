# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Offline lifecycle bridge checks using the real persistent pilot ledger."""

import copy
import json

import pytest

from robots.libero.research.library import digest
from robots.univtac.pilot import Pilot, execution
from robots.univtac.toolkit import native_catalog


def evidence():
    return {
        "controller": {
            "action_repeat": 2,
            "command_limit": 300,
            "sandbox_image": "sha256:" + "a" * 64,
        },
        "code_revision": {"git_head": "fixed", "sources": {"control.py": "b" * 64}},
        "memory": {"mode": "empty_read_only", "shared": False, "file_tools": False},
    }


def profile(model):
    return {
        "planner": "codex_sdk" if model == "gpt-6-astra" else "openai",
        "model": model,
        "reasoning_effort": "high",
        "base_url": None if model == "gpt-6-astra" else "https://example.invalid/v1",
        "max_tokens": 4096,
    }


def scene(offset=0):
    return {
        "model": {"revision": "pinned"},
        "state": {"pose": [offset, 0, 0]},
        "physics": {"dt": 1 / 120},
        "sensors": {"initial_hash": "sensor"},
        "rng": {"seed": 100},
        "assets": {"mesh": "hash"},
    }


def begin(pilot, output, cell_id="dev-03", **overrides):
    cell = pilot._cell(cell_id)
    params = {
        "pilot_root": pilot.root,
        "cell_id": cell_id,
        "output_dir": output,
        "model": cell["model"],
        "task": cell["task"],
        "seed": cell["seed"],
        "selected": None,
        "budget": execution.BUDGET,
        "model_profile_settings": profile(cell["model"]),
        "actual_evidence": evidence(),
    }
    params.update(overrides)
    return execution.before_start(**params)


def freeze_after_development(pilot, tmp_path, parameters=None):
    paths = {}
    for name in ("sensors", "actions", "feedback"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({name: "sanitized"}))
        paths[name] = str(path)
    inputs = []
    for cell in pilot.manifest["cells"][:6]:
        attempt = pilot.reserve_episode(cell["id"], cell["id"])
        pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt, {"termination_reason": "completed", "maker_inputs": paths}
        )
        if cell["stage"] != "smoke":
            inputs.append(attempt)
    maker_budget = {"max_calls": 1, "max_tokens": 100}
    for variant in ("G0", "G1"):
        call = pilot.reserve_offline(
            "maker", variant, inputs, maker_budget=maker_budget, max_tokens=100
        )
        pilot.finish_offline(call, {"status": "completed"})
    generated = {
        "name": "sensor_contact",
        "origin": "generated",
        "source": "def run(frames, params): return {}",
        "description": "Contact image statistics",
        "parameters": {"type": "object", "properties": {}},
    }
    generated["version"] = digest(
        [
            {
                key: generated[key]
                for key in ("name", "description", "parameters", "source")
            }
        ]
    )
    base = native_catalog()
    bundle = {
        "conditions": {
            name: {
                "tools": base + ([generated] if name in "DE" else []),
                "guidance": f"fixed-{name}",
                "parameters": parameters or {},
            }
            for name in "CDEF"
        },
        **evidence(),
        "models": {
            "budget": execution.BUDGET,
            "profiles": {
                model: profile(model) for model in ("gpt-6-astra", "qwen3.8-max")
            },
        },
        "base_tool": generated,
        "maker_budget": maker_budget,
        "maker_input_attempts": inputs,
        "validation_evidence": {"replay": "passed"},
    }
    return pilot.freeze(bundle), bundle


def test_native_development_reserves_before_reset_and_restores_without_recharge(
    tmp_path,
):
    pilot = Pilot.create(tmp_path / "pilot")
    run = begin(pilot, tmp_path / "run")
    assert pilot.summary()["episodes_reserved"] == 1
    assert run.selected == native_catalog() and run.guidance == ""
    assert run.record["actual_evidence"] == evidence()
    assert run.sandbox_image == evidence()["controller"]["sandbox_image"]
    run.after_reset({"scene": scene(), "official_success": False})
    restored = execution.restore_from_output(tmp_path / "run")
    assert restored.attempt_id == run.attempt_id
    outcome = restored.after_finish(
        {"finish": {"status": "success"}, "environment_success": False}
    )
    assert outcome["termination_reason"] == "completed"
    assert outcome["native_success"] is False
    assert pilot.summary()["episodes_reserved"] == pilot.summary()["finished"] == 1
    assert restored.after_finish({"termination_reason": "failed"}) == outcome
    assert execution.restore_from_output(tmp_path / "ordinary") is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "qwen3.8-max"},
        {"task": "insert_tube"},
        {"seed": 100},
        {"budget": {**execution.BUDGET, "max_turns": 25}},
        {"budget": {**execution.BUDGET, "planner_timeout_s": 600}},
        {"budget": {**execution.BUDGET, "model_request_timeout_s": 30}},
        {"budget": {**execution.BUDGET, "model_request_timeout_s": 180}},
        {"selected": []},
    ],
)
def test_wrong_cell_budget_or_baseline_rejected_before_simulator(tmp_path, overrides):
    pilot = Pilot.create(tmp_path / "pilot")
    with pytest.raises(ValueError):
        begin(pilot, tmp_path / "run", **overrides)
    assert pilot.summary()["episodes_reserved"] == 0


def test_provisional_requires_explicit_selection(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    with pytest.raises(ValueError, match="explicit provisional"):
        begin(pilot, tmp_path / "run", "dev-05")
    run = begin(pilot, tmp_path / "run", "dev-05", selected=native_catalog())
    run.after_finish({"termination_reason": "setup_failure"})
    assert pilot.summary()["finished"] == 1


def test_real_cli_float_timeouts_preserve_fixed_budget(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    run = begin(
        pilot,
        tmp_path / "run",
        budget={
            "max_turns": 60,
            "planner_timeout_s": 3600.0,
            "model_request_timeout_s": 300.0,
        },
    )
    assert run.record["budget"] == execution.BUDGET


def test_restoring_historical_timeout_does_not_rewrite_or_recharge(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    run = begin(pilot, tmp_path / "historical")
    run.after_finish({"termination_reason": "timeout"})
    path = run.output_dir / "pilot-attempt.json"
    record = json.loads(path.read_text())
    record["budget"]["model_request_timeout_s"] = 180
    path.write_text(json.dumps(record))
    original = path.read_bytes()
    restored = execution.restore_from_output(run.output_dir)
    assert restored.record["budget"]["model_request_timeout_s"] == 180
    assert restored.record["outcome"]["termination_reason"] == "timeout"
    assert path.read_bytes() == original
    assert pilot.summary()["episodes_reserved"] == pilot.summary()["finished"] == 1


def test_frozen_condition_applies_tools_guidance_and_actual_model_profile(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    version, bundle = freeze_after_development(pilot, tmp_path)
    wrong_profile = {**profile("qwen3.8-max"), "max_tokens": 2048}
    with pytest.raises(ValueError, match="model profile"):
        begin(
            pilot,
            tmp_path / "bad",
            "dev-07",
            freeze_id=version,
            model_profile_settings=wrong_profile,
        )
    with pytest.raises(ValueError, match="Selected tools differ"):
        begin(
            pilot,
            tmp_path / "bad",
            "dev-07",
            freeze_id=version,
            selected=native_catalog(),
        )
    run = begin(pilot, tmp_path / "run", "dev-07", freeze_id=version)
    assert run.selected == bundle["conditions"]["E"]["tools"]
    assert run.guidance == "fixed-E" and run.parameters == {}
    modified = run.selected
    modified.clear()
    assert run.selected


def test_unimplemented_condition_parameters_are_rejected(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    version, _ = freeze_after_development(pilot, tmp_path, parameters={"unused": 1})
    with pytest.raises(ValueError, match="parameters must be empty"):
        begin(pilot, tmp_path / "run", "dev-07", freeze_id=version)


def test_frozen_execution_ignores_display_changes_but_uses_original_snapshot(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    version, bundle = freeze_after_development(pilot, tmp_path)
    expected = bundle["conditions"]["E"]["tools"]
    selected = copy.deepcopy(expected)
    for tool in selected:
        tool.update(invoked=True, validation="invoked", example="new display example")
    run = begin(pilot, tmp_path / "run", "dev-07", freeze_id=version, selected=selected)
    assert run.selected == expected and run.selected != selected
    stored = json.loads((run.output_dir / "pilot-attempt.json").read_text())
    assert stored["selected"] == expected
    selected[-1]["source"] = "changed after reservation"
    assert run.selected == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "sensor_renamed"),
        ("origin", "native"),
        ("version", "different"),
        ("source", "def run(frames, params): return {'changed': True}"),
        ("description", "different instructions"),
        (
            "parameters",
            {"type": "object", "properties": {"threshold": {"type": "number"}}},
        ),
        ("dependencies", ["move_eef"]),
    ],
)
def test_changed_frozen_execution_field_is_rejected_before_charging(
    tmp_path, field, value
):
    pilot = Pilot.create(tmp_path / "pilot")
    version, bundle = freeze_after_development(pilot, tmp_path)
    selected = copy.deepcopy(bundle["conditions"]["E"]["tools"])
    selected[-1][field] = value
    with pytest.raises(ValueError, match="Selected tools differ"):
        begin(pilot, tmp_path / "run", "dev-07", freeze_id=version, selected=selected)
    assert pilot.summary()["episodes_reserved"] == 6


@pytest.mark.parametrize("part", [None, "controller", "code_revision", "memory"])
def test_frozen_runtime_drift_is_rejected_before_charging(tmp_path, part):
    pilot = Pilot.create(tmp_path / "pilot")
    version, _ = freeze_after_development(pilot, tmp_path)
    actual = evidence() if part is not None else None
    if part is not None:
        actual[part]["changed"] = True
    with pytest.raises(ValueError, match="controller/code/memory evidence"):
        begin(
            pilot, tmp_path / "run", "dev-07", freeze_id=version, actual_evidence=actual
        )
    assert pilot.summary()["episodes_reserved"] == 6


def test_scene_mismatch_finishes_attempt_before_execution(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    version, _ = freeze_after_development(pilot, tmp_path)
    for cell in pilot.manifest["cells"][6:8]:
        run = begin(pilot, tmp_path / cell["id"], cell["id"], freeze_id=version)
        run.after_reset({"scene": scene()})
        run.after_finish({"status": "completed", "interface_validation_passed": True})
    first, second = pilot.manifest["cells"][8:10]
    run = begin(pilot, tmp_path / "first", first["id"], freeze_id=version)
    run.after_reset({"scene": scene()})
    run.after_finish({"status": "completed", "official_success": True})
    run = begin(pilot, tmp_path / "second", second["id"], freeze_id=version)
    with pytest.raises(ValueError, match="scene mismatch"):
        run.after_reset({"scene": scene(offset=1)})
    row = pilot.summary()["rows"][-1]
    assert (
        row["termination_reason"] == "scene_mismatch" and row["scene_matched"] is False
    )


@pytest.mark.parametrize(
    "status,expected",
    [
        ("network_failure", "network_failure"),
        ("timeout", "timeout"),
        ("aborted", "aborted"),
        ("configuration_error", "setup_failure"),
        ("error", "failed"),
        ("abnormal_exit", "abnormal_exit"),
    ],
)
def test_failure_reasons_and_official_success_remain_separate(
    tmp_path, status, expected
):
    pilot = Pilot.create(tmp_path / "pilot")
    run = begin(pilot, tmp_path / "run")
    result = run.after_finish(
        {"status": status, "finish": {"status": "success"}, "native_success": True}
    )
    assert result["termination_reason"] == expected and result["native_success"] is None


def test_restore_recovers_ledger_finish_after_metadata_write_interruption(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    run = begin(pilot, tmp_path / "run")
    before = copy.deepcopy(run.record)
    run.after_finish({"status": "network_failure"})
    (run.output_dir / "pilot-attempt.json").write_text(json.dumps(before))
    restored = execution.restore_from_output(run.output_dir)
    assert (
        restored.after_finish({"status": "abnormal_exit"})["termination_reason"]
        == "network_failure"
    )
    assert pilot.summary()["finished"] == 1


def test_missing_scene_and_failed_metadata_write_still_leave_charged_attempts(
    tmp_path, monkeypatch
):
    pilot = Pilot.create(tmp_path / "pilot")
    run = begin(pilot, tmp_path / "run")
    with pytest.raises(KeyError):
        run.after_reset({})
    assert pilot.summary()["termination_counts"] == {"setup_failure": 1}

    def failed_write(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(execution, "write_json_atomic", failed_write)
    with pytest.raises(OSError, match="disk unavailable"):
        begin(pilot, tmp_path / "run-2", "dev-04")
    assert pilot.summary()["episodes_reserved"] == pilot.summary()["finished"] == 2
