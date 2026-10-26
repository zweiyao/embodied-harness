# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Offline protocol tests; no simulator, API or generated code is executed."""

import json
import subprocess
import sys
from collections import Counter

import pytest

from robots.univtac.pilot import Pilot, amended_manifest, default_manifest, digest


def scene(offset=0):
    return {
        "model": {"revision": "test"},
        "state": {"pose": [offset, 0, 0]},
        "physics": {"dt": 0.01},
        "sensors": {"resolution": [4, 4]},
        "rng": {"state": "fixed"},
        "assets": {"mesh": "hash"},
    }


def development(pilot, tmp_path, *, missing_scene=None):
    inputs = {}
    for name in ("sensors", "actions", "feedback"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({name: ["sanitized"]}))
        inputs[name] = str(path)
    attempts = []
    for cell in pilot.manifest["cells"][:6]:
        attempt = pilot.reserve_episode(cell["id"], cell["id"])
        failed_before_scene = missing_scene and cell["id"] == missing_scene[0]
        if not failed_before_scene:
            pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt,
            {
                "termination_reason": missing_scene[1]
                if failed_before_scene
                else "completed",
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


@pytest.mark.parametrize(
    "cell_id,reason,allowed",
    [
        ("dev-01", "setup_failure", True),
        ("dev-02", "setup_failure", True),
        ("dev-01", "aborted", False),
        ("dev-01", "network_failure", False),
        ("dev-03", "setup_failure", False),
        ("dev-05", "setup_failure", False),
        ("dev-07", "setup_failure", False),
    ],
)
def test_only_smoke_setup_failure_may_lack_scene_before_holdout(
    tmp_path, cell_id, reason, allowed
):
    pilot = Pilot.create(tmp_path / "pilot")
    attempts = development(pilot, tmp_path, missing_scene=(cell_id, reason))
    version = pilot.freeze(bundle(attempts, pilot))
    for cell in pilot.manifest["cells"][6:8]:
        attempt = pilot.reserve_episode(cell["id"], cell["id"], version)
        if cell["id"] != cell_id:
            pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt,
            {
                "termination_reason": reason if cell["id"] == cell_id else "completed",
                "native_success": None,
                "interface_validation_passed": True,
            },
        )
    reopened = Pilot(pilot.root)
    summary = reopened.summary()
    assert summary["episodes_reserved"] == summary["finished"] == 8
    failure = next(row for row in summary["rows"] if row["id"] == cell_id)
    assert failure["scene_fingerprint"] is None
    assert failure["termination_reason"] == reason
    with pytest.raises(ValueError, match="already"):
        reopened.reserve_episode(cell_id, "retry", version)
    formal = pilot.manifest["cells"][8]["id"]
    if allowed:
        reopened.reserve_episode(formal, "heldout", version)
        assert reopened.summary()["episodes_reserved"] == 9
    else:
        with pytest.raises(ValueError, match="development scene evidence is missing"):
            reopened.reserve_episode(formal, "heldout", version)
        assert reopened.summary()["episodes_reserved"] == 8


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


def test_connectivity_checks_need_no_episodes_and_spend_the_shared_request_budget(
    tmp_path,
):
    pilot = Pilot.create(tmp_path / "pilot")
    request = pilot.reserve_offline("connectivity", None, [])
    pilot.finish_offline(request, {"error": "network failure"})
    for _ in range(79):
        pilot.reserve_offline("connectivity", None, [])
    summary = Pilot(pilot.root).summary()
    assert summary["episodes_reserved"] == 0
    assert summary["offline_requests"] == 80
    with pytest.raises(ValueError, match="budget exhausted"):
        pilot.reserve_offline("connectivity", None, [])


@pytest.mark.parametrize(
    "variant,attempts,maker_budget",
    [
        ("G0", [], None),
        ("G1", [], None),
        (None, ["dev-01"], None),
        (None, [], {"max_calls": 1, "max_tokens": 10}),
    ],
)
def test_connectivity_cannot_claim_episode_inputs_or_a_maker_branch(
    tmp_path, variant, attempts, maker_budget
):
    pilot = Pilot.create(tmp_path / "pilot")
    with pytest.raises(ValueError, match="connectivity checks require"):
        pilot.reserve_offline(
            "connectivity", variant, attempts, maker_budget=maker_budget
        )
    assert pilot.summary()["offline_requests"] == 0


def test_frozen_batch_allows_only_input_free_connectivity_within_same_budget(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    attempts = development(pilot, tmp_path)
    pilot.freeze(bundle(attempts, pilot))
    before = pilot.summary()["offline_requests"]
    request = pilot.reserve_offline("connectivity", None, [])
    pilot.finish_offline(request, {"ok": False, "status": "network_failure"})
    assert pilot.summary()["offline_requests"] == before + 1
    with pytest.raises(ValueError, match="no inputs"):
        pilot.reserve_offline("connectivity", None, attempts)
    with pytest.raises(ValueError, match="closed after freezing"):
        pilot.reserve_offline("maker", "G1", attempts)
    for _ in range(80 - before - 1):
        pilot.reserve_offline("connectivity", None, [])
    with pytest.raises(ValueError, match="budget exhausted"):
        pilot.reserve_offline("connectivity", None, [])


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


def pending_interface_reviews(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    version = pilot.freeze(bundle(development(pilot, tmp_path), pilot))
    attempts, reports = [], []
    for cell in pilot.manifest["cells"][6:8]:
        attempt = pilot.reserve_episode(cell["id"], cell["id"], version)
        pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt, {"termination_reason": "completed", "native_success": True}
        )
        report = tmp_path / f"{cell['id']}-interface.md"
        report.write_text(
            "Recorded declarations, parameters and outputs were reviewed."
        )
        attempts.append(attempt)
        reports.append(report)
    return pilot, version, attempts, reports


def test_post_run_interface_review_unblocks_holdout_without_rewriting_finish(tmp_path):
    pilot, version, attempts, reports = pending_interface_reviews(tmp_path)
    formal = pilot.manifest["cells"][8]["id"]
    with pytest.raises(ValueError, match="validations must pass"):
        pilot.reserve_episode(formal, "heldout", version)
    for attempt, report in zip(attempts, reports, strict=True):
        pilot.record_interface_validation(attempt, True, report)
    events = [
        json.loads(line)
        for line in (pilot.root / "events.jsonl").read_text().splitlines()
    ]
    finished = [
        event
        for event in events
        if event["kind"] == "finished" and event["id"] in attempts
    ]
    assert len(finished) == 2
    assert all(
        "interface_validation_passed" not in event["outcome"] for event in finished
    )
    validations = [event for event in events if event["kind"] == "interface_validation"]
    assert len(validations) == 2 and all(
        event["freeze_id"] == version for event in validations
    )
    assert all(
        event["scene_fingerprint"] and len(event["evidence"]["sha256"]) == 64
        for event in validations
    )
    assert all(
        row["interface_validation_passed"] for row in pilot.summary()["rows"][6:8]
    )
    pilot.reserve_episode(formal, "heldout", version)
    assert pilot.summary()["episodes_reserved"] == 9


@pytest.mark.parametrize("change", ["modified", "removed"])
def test_interface_evidence_is_rechecked_before_every_formal_reservation(
    tmp_path, change
):
    pilot, version, attempts, reports = pending_interface_reviews(tmp_path)
    for attempt, report in zip(attempts, reports, strict=True):
        pilot.record_interface_validation(attempt, True, report)
    if change == "modified":
        reports[0].write_text("Changed after acceptance")
    else:
        reports[0].unlink()
    with pytest.raises(ValueError, match="interface validation"):
        pilot.reserve_episode(pilot.manifest["cells"][8]["id"], "heldout", version)
    assert pilot.summary()["episodes_reserved"] == 8


def test_failed_or_duplicate_review_cannot_be_replaced_by_success(tmp_path):
    pilot, version, attempts, reports = pending_interface_reviews(tmp_path)
    pilot.record_interface_validation(attempts[0], False, reports[0])
    with pytest.raises(ValueError, match="already recorded"):
        pilot.record_interface_validation(attempts[0], True, reports[0])
    pilot.record_interface_validation(attempts[1], True, reports[1])
    with pytest.raises(ValueError, match="validations must pass"):
        pilot.reserve_episode(pilot.manifest["cells"][8]["id"], "heldout", version)
    assert pilot.summary()["rows"][6]["native_success"] is True
    assert pilot.summary()["rows"][6]["interface_validation_passed"] is False


def test_interface_review_requires_finished_validation_and_initial_scene(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    development_attempts = development(pilot, tmp_path)
    version = pilot.freeze(bundle(development_attempts, pilot))
    report = tmp_path / "report.md"
    report.write_text("Review")
    with pytest.raises(ValueError, match="validate-stage"):
        pilot.record_interface_validation(development_attempts[0], True, report)
    attempt = pilot.reserve_episode("dev-07", "validation", version)
    with pytest.raises(ValueError, match="ended"):
        pilot.record_interface_validation(attempt, True, report)
    pilot.finish_episode(attempt, {"termination_reason": "setup_failure"})
    with pytest.raises(ValueError, match="matching freeze and scene"):
        pilot.record_interface_validation(attempt, True, report)


def test_interface_review_rejects_missing_empty_evidence_and_nonboolean_decision(
    tmp_path,
):
    pilot, _, attempts, reports = pending_interface_reviews(tmp_path)
    with pytest.raises(ValueError, match="boolean"):
        pilot.record_interface_validation(attempts[0], "true", reports[0])
    reports[0].write_text("")
    with pytest.raises(ValueError, match="must not be empty"):
        pilot.record_interface_validation(attempts[0], True, reports[0])
    reports[0].unlink()
    with pytest.raises(FileNotFoundError):
        pilot.record_interface_validation(attempts[0], True, reports[0])
    assert not any(
        "interface_validation_passed" in row for row in pilot.summary()["rows"][6:8]
    )


def test_interface_review_cannot_replace_legacy_decision_or_accept_changed_freeze(
    tmp_path,
):
    pilot = Pilot.create(tmp_path / "pilot")
    version = pilot.freeze(bundle(development(pilot, tmp_path), pilot))
    finish_validation(pilot, version)
    report = tmp_path / "review.md"
    report.write_text("review")
    attempt = pilot.summary()["rows"][6]["attempt_id"]
    with pytest.raises(ValueError, match="already recorded"):
        pilot.record_interface_validation(attempt, False, report)

    pending_root = tmp_path / "pending"
    pending_root.mkdir()
    other, version, attempts, reports = pending_interface_reviews(pending_root)
    frozen = other.root / f"freeze-{version}.json"
    payload = json.loads(frozen.read_text())
    payload["code_revision"] = "modified"
    frozen.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="hash mismatch"):
        other.record_interface_validation(attempts[0], True, reports[0])


def test_validate_interface_cli_records_explicit_decision(tmp_path):
    pilot, _, attempts, reports = pending_interface_reviews(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "robots.univtac.pilot",
            str(pilot.root),
            "validate-interface",
            attempts[0],
            str(reports[0]),
            "--passed",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert pilot.summary()["rows"][6]["interface_validation_passed"] is True
    assert pilot.summary()["episodes_reserved"] == 8


def infrastructure(pilot, *, passed=True):
    for cell_id in ("infra-01", "infra-02"):
        attempt = pilot.reserve_episode(cell_id, cell_id)
        pilot.record_scene(attempt, scene())
        pilot.finish_episode(
            attempt,
            {"termination_reason": "completed", "checkpoint_validation_passed": passed},
        )


def test_budget_amendment_preserves_failed_attempts_and_original_records(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    attempt = pilot.reserve_episode("dev-01", "original")
    pilot.finish_episode(attempt, {"termination_reason": "setup_failure"})
    original = (pilot.root / "manifest.json").read_bytes()
    prefix = (pilot.root / "events.jsonl").read_bytes()
    old_reader = Pilot(pilot.root)
    version = pilot.amend_budget("User approved 12 development / 24 Max / 4 GPT")
    reopened = Pilot(pilot.root)
    assert reopened.manifest == amended_manifest()
    assert (pilot.root / "manifest.json").read_bytes() == original
    assert (pilot.root / "events.jsonl").read_bytes().startswith(prefix)
    summary = old_reader.summary()
    assert summary["schema_version"] == 2
    assert summary["episodes_reserved"] == summary["finished"] == 1
    assert summary["termination_counts"] == {"setup_failure": 1}
    assert summary["episode_limit"] == 40 and summary["development_limit"] == 12
    assert summary["holdout_limits"] == {"qwen3.8-max": 24, "gpt-6-astra": 4}
    assert len(reopened.manifest["cells"]) == 40
    assert reopened.manifest["cells"][:8] == default_manifest()["cells"][:8]
    assert len({c["id"] for c in reopened.manifest["cells"]}) == 40
    assert [(c["id"], c["seed"]) for c in reopened.manifest["cells"][8:12]] == [
        ("infra-01", 2),
        ("infra-02", 2),
        ("repair-01", 6),
        ("repair-02", 7),
    ]
    amendment = json.loads(
        (pilot.root / f"manifest-amendment-{version}.json").read_text()
    )
    assert digest(amendment) == version and amendment["reason"].startswith(
        "User approved"
    )
    with pytest.raises(ValueError, match="already been used"):
        reopened.reserve_episode("dev-01", "retry")
    with pytest.raises(ValueError, match="already been amended"):
        reopened.amend_budget("Retry")


def test_v1_is_unchanged_and_orphan_amendment_is_not_effective(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    payload = {
        "original_manifest_sha256": digest(default_manifest()),
        "manifest": amended_manifest(),
        "reason": "User approved revision",
    }
    path = pilot.root / f"manifest-amendment-{digest(payload)}.json"
    path.write_text(json.dumps(payload))
    reopened = Pilot(pilot.root)
    assert reopened.manifest == default_manifest()
    assert reopened.summary()["schema_version"] == 1
    assert reopened.summary()["holdout_limits"] == {"qwen3.8-max": 24, "gpt-6-astra": 8}
    # Recover the fully written orphan without overwriting its bytes.
    original = path.read_bytes()
    assert reopened.amend_budget(payload["reason"]) == digest(payload)
    assert path.read_bytes() == original


def test_old_pilot_object_cannot_reserve_removed_cell_after_amendment(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    stale = Pilot(pilot.root)
    removed = "gpt-6-astra-insert_tube-101-C"
    assert stale._cell(removed)["stage"] == "holdout"
    pilot.amend_budget("User approved revision")
    with pytest.raises(ValueError, match="unknown protocol cell"):
        stale.reserve_episode(removed, "old-reader")
    assert pilot.summary()["episodes_reserved"] == 0


def test_missing_ledger_is_not_recreated_as_an_unused_batch(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    (pilot.root / "events.jsonl").unlink()
    with pytest.raises(FileNotFoundError):
        Pilot(pilot.root)
    with pytest.raises(FileNotFoundError):
        pilot.summary()
    assert not (pilot.root / "events.jsonl").exists()


@pytest.mark.parametrize("change", ["modified", "missing", "forged", "duplicate"])
def test_committed_amendment_tampering_fails_closed(tmp_path, change):
    pilot = Pilot.create(tmp_path / "pilot")
    version = pilot.amend_budget("User approved revision")
    path = pilot.root / f"manifest-amendment-{version}.json"
    payload = json.loads(path.read_text())
    if change == "missing":
        path.unlink()
    elif change == "duplicate":
        with (pilot.root / "events.jsonl").open("a") as file:
            file.write(json.dumps({"kind": "budget_amendment", "id": version}) + "\n")
    else:
        payload["manifest"]["max_episodes"] = 100
        if change == "modified":
            path.write_text(json.dumps(payload))
        else:
            forged = digest(payload)
            (pilot.root / f"manifest-amendment-{forged}.json").write_text(
                json.dumps(payload)
            )
            events = json.loads((pilot.root / "events.jsonl").read_text())
            events["id"] = forged
            (pilot.root / "events.jsonl").write_text(json.dumps(events) + "\n")
    with pytest.raises((ValueError, FileNotFoundError)):
        Pilot(pilot.root)
    with pytest.raises((ValueError, FileNotFoundError)):
        pilot.summary()


def test_budget_amendment_requires_authorization_reason_and_no_active_attempt(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    for reason in (None, "", " "):
        with pytest.raises(ValueError, match="authorization reason"):
            pilot.amend_budget(reason)
    pilot.reserve_episode("dev-01", "active")
    with pytest.raises(ValueError, match="active attempt"):
        pilot.amend_budget("User approved revision")
    assert not list(pilot.root.glob("manifest-amendment-*.json"))


def test_budget_amendment_rejects_frozen_batch_and_used_holdout_history(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    pilot.freeze(bundle(development(pilot, tmp_path), pilot))
    with pytest.raises(ValueError, match="precede freezing"):
        pilot.amend_budget("User approved revision")
    # Even an invalid legacy ledger lacking its freeze event cannot amend used holdout.
    other = Pilot.create(tmp_path / "other")
    with (other.root / "events.jsonl").open("a") as file:
        for event in (
            {
                "kind": "reserved",
                "id": "historical",
                "cell": default_manifest()["cells"][8]["id"],
            },
            {"kind": "finished", "id": "historical"},
        ):
            file.write(json.dumps(event) + "\n")
    with pytest.raises(ValueError, match="used holdout"):
        other.amend_budget("User approved revision")


@pytest.mark.parametrize("checkpoint", [None, False])
def test_v2_freeze_requires_both_successful_checkpoints(tmp_path, checkpoint):
    pilot = Pilot.create(tmp_path / "pilot")
    pilot.amend_budget("User approved revision")
    frozen = bundle(development(pilot, tmp_path), pilot)
    if checkpoint is not None:
        infrastructure(pilot, passed=checkpoint)
    with pytest.raises(ValueError, match="both infrastructure checkpoints"):
        pilot.freeze(frozen)
    assert not list(pilot.root.glob("freeze-*.json"))


@pytest.mark.parametrize("use_repair", [False, True])
def test_v2_optional_repairs_may_be_skipped_but_used_attempts_must_end(
    tmp_path, use_repair
):
    pilot = Pilot.create(tmp_path / "pilot")
    pilot.amend_budget("User approved revision")
    frozen = bundle(development(pilot, tmp_path), pilot)
    infrastructure(pilot)
    if use_repair:
        attempt = pilot.reserve_episode("repair-01", "repair")
        with pytest.raises(ValueError, match="active attempt"):
            pilot.freeze(frozen)
        pilot.record_scene(attempt, scene())
        pilot.finish_episode(attempt, {"termination_reason": "network_failure"})
    version = pilot.freeze(frozen)
    with pytest.raises(ValueError, match="closed after freezing"):
        pilot.reserve_episode("repair-02", "late-repair")
    finish_validation(pilot, version)
    formal = next(c["id"] for c in pilot.manifest["cells"] if c["stage"] == "holdout")
    pilot.reserve_episode(formal, "formal", version)
    assert pilot.summary()["episodes_reserved"] == 11 + int(use_repair)


def test_v2_used_repair_still_needs_scene_before_holdout(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    pilot.amend_budget("User approved revision")
    frozen = bundle(development(pilot, tmp_path), pilot)
    infrastructure(pilot)
    attempt = pilot.reserve_episode("repair-01", "repair")
    pilot.finish_episode(attempt, {"termination_reason": "setup_failure"})
    version = pilot.freeze(frozen)
    finish_validation(pilot, version)
    formal = next(c["id"] for c in pilot.manifest["cells"] if c["stage"] == "holdout")
    with pytest.raises(ValueError, match="development scene evidence is missing"):
        pilot.reserve_episode(formal, "formal", version)


def test_amend_budget_cli_records_user_reason(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "robots.univtac.pilot",
            str(pilot.root),
            "amend-budget",
            "--reason",
            "User approved 12/24/4",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert Pilot(pilot.root).manifest == amended_manifest()
    event = json.loads((pilot.root / "events.jsonl").read_text())
    assert (
        event["kind"] == "budget_amendment"
        and event["reason"] == "User approved 12/24/4"
    )
