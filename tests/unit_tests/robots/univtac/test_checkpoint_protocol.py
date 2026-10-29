# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Checkpoint retries retain failures and bind the new qualification evidence."""

import hashlib
import json

import pytest

from robots.univtac.pilot import Pilot, digest
from robots.univtac.pilot.checkpoint_protocol import verify_qualification


def protocol():
    return {
        "schema_version": 1,
        "name": "univtac-checkpoint-qualification",
        "snapshot_schema_version": 2,
        "cells": ["infra-03", "infra-04"],
        "task": "insert_hole",
        "seed": 2,
        "position_limit_m": 0.00002078125,
    }


def failed_pair(tmp_path):
    pilot = Pilot.create(tmp_path / "pilot")
    pilot.amend_budget("Approved 12/24/4 allocation")
    for cell in ("infra-01", "infra-02"):
        attempt = pilot.reserve_episode(cell, cell)
        pilot.finish_episode(
            attempt,
            {"termination_reason": "failed", "checkpoint_validation_passed": False},
        )
    return pilot


def qualify(pilot):
    refs = []
    root = pilot.root / "snapshot"
    root.mkdir()
    for cell, role in zip(
        ("infra-03", "infra-04"), ("capture", "restore"), strict=True
    ):
        attempt = pilot.reserve_episode(cell, cell)
        pilot.record_scene(
            attempt,
            {
                key: {"test": "fixed"}
                for key in ("model", "state", "physics", "sensors", "rng", "assets")
            },
        )
        if role == "capture":
            native = root / "native.npz"
            native.write_bytes(b"fixture native arrays")
            measurement = {
                "native": {
                    "path": str(native),
                    "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                }
            }
            branch = {
                "anchor": measurement,
                "stationary": [measurement] * 4,
                "steps": [{"scene": measurement}] * 3,
            }
            for name in ("state", "scene", "baseline", "protocol"):
                (root / f"{name}.json").write_text(
                    json.dumps(
                        protocol()
                        if name == "protocol"
                        else branch
                        if name == "baseline"
                        else {}
                    )
                )
            (root / "dump").mkdir()
            for index in range(9):
                (root / "dump" / str(index)).write_bytes(b"pinned test state")
            saved = {
                "schema_version": 2,
                "capture_attempt_id": attempt,
                "files": {
                    str(path.relative_to(root)): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in root.rglob("*")
                    if path.is_file()
                },
            }
            (root / "manifest.json").write_text(json.dumps(saved))
        report = {
            "passed": True,
            "protocol_sha256": digest(protocol()),
            "snapshot_sha256": digest(saved),
            "attempt_id": attempt,
            "role": role,
            "cell_id": cell,
            "checks": [{"name": "test measurement", "passed": True}],
            "snapshot_manifest": {
                "path": str(root / "manifest.json"),
                "sha256": hashlib.sha256(
                    (root / "manifest.json").read_bytes()
                ).hexdigest(),
            },
            "branch_evidence": {
                "path": str(root / "baseline.json"),
                "sha256": hashlib.sha256(
                    (root / "baseline.json").read_bytes()
                ).hexdigest(),
            },
        }
        if refs:
            report["capture_report_sha256"] = refs[0]["sha256"]
        path = pilot.root / f"{cell}-report.json"
        path.write_text(json.dumps(report))
        ref = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        refs.append(ref)
        pilot.finish_episode(
            attempt,
            {
                "termination_reason": "completed",
                "checkpoint_validation_passed": True,
                "checkpoint_evidence": ref,
            },
        )
    return refs


def events(pilot):
    return [
        json.loads(line)
        for line in (pilot.root / "events.jsonl").read_text().splitlines()
    ]


def test_recheck_preserves_failures_and_limit_and_survives_reopen(tmp_path):
    pilot = failed_pair(tmp_path)
    stale = Pilot(pilot.root)
    original = (pilot.root / "manifest.json").read_bytes()
    prefix = (pilot.root / "events.jsonl").read_bytes()
    version = pilot.amend_checkpoint_validation(
        protocol(), "Restore omitted command targets"
    )
    reopened = Pilot(pilot.root)
    assert reopened.manifest["schema_version"] == 3
    assert reopened.summary()["episodes_reserved"] == 2
    assert reopened.summary()["termination_counts"] == {"failed": 2}
    assert reopened.summary()["holdout_limits"] == {"qwen3.8-max": 24, "gpt-6-astra": 4}
    assert reopened.summary()["development_limit"] == 12
    assert len(reopened.manifest["cells"]) == 40
    assert (pilot.root / "manifest.json").read_bytes() == original
    assert (pilot.root / "events.jsonl").read_bytes().startswith(prefix)
    payload = json.loads(
        (pilot.root / f"checkpoint-amendment-{version}.json").read_text()
    )
    assert payload["protocol"] == protocol()
    with pytest.raises(ValueError, match="unknown protocol cell"):
        stale.reserve_episode("repair-01", "stale")
    with pytest.raises(ValueError, match="unamended"):
        reopened.amend_checkpoint_validation(protocol(), "repeat")
    qualify(reopened)
    verify_qualification(reopened.manifest, events(reopened))


@pytest.mark.parametrize(
    "case", ["no_v2", "no_pair", "active", "used_repair", "frozen", "holdout"]
)
def test_revision_cannot_erase_used_slots_or_follow_freeze(tmp_path, case):
    pilot = (
        failed_pair(tmp_path)
        if case not in ("no_v2", "no_pair")
        else Pilot.create(tmp_path / "pilot")
    )
    if case == "no_pair":
        pilot.amend_budget("approved")
    if case in ("active", "used_repair"):
        attempt = pilot.reserve_episode("repair-01", "repair")
        if case == "used_repair":
            pilot.finish_episode(attempt, {"termination_reason": "failed"})
    if case in ("frozen", "holdout"):
        with (pilot.root / "events.jsonl").open("a") as stream:
            extra = (
                [{"kind": "frozen", "id": "test"}]
                if case == "frozen"
                else [
                    {
                        "kind": "reserved",
                        "id": "formal",
                        "cell": "qwen3.8-max-insert_tube-100-C",
                    },
                    {
                        "kind": "finished",
                        "id": "formal",
                        "outcome": {"termination_reason": "failed"},
                    },
                ]
            )
            for event in extra:
                stream.write(json.dumps(event) + "\n")
    before = (pilot.root / "events.jsonl").read_bytes()
    with pytest.raises(ValueError):
        pilot.amend_checkpoint_validation(protocol(), "revision")
    assert (pilot.root / "events.jsonl").read_bytes() == before


def test_protocol_cannot_change_after_registration(tmp_path):
    pilot = failed_pair(tmp_path)
    version = pilot.amend_checkpoint_validation(protocol(), "revision")
    path = pilot.root / f"checkpoint-amendment-{version}.json"
    payload = json.loads(path.read_text())
    payload["protocol"]["position_limit_m"] = 1
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="evidence differs"):
        Pilot(pilot.root)


@pytest.mark.parametrize(
    "change",
    [
        "file",
        "wrong_snapshot",
        "wrong_protocol",
        "wrong_capture",
        "wrong_attempt",
        "false_pass",
        "missing_ref",
        "missing_snapshot",
        "changed_state",
        "empty_checks",
        "failed_check",
    ],
)
def test_qualification_requires_matching_immutable_evidence(tmp_path, change):
    pilot = failed_pair(tmp_path)
    pilot.amend_checkpoint_validation(protocol(), "revision")
    refs = qualify(pilot)
    records = events(pilot)
    if change == "missing_snapshot":
        (pilot.root / "snapshot/manifest.json").unlink()
    elif change == "changed_state":
        (pilot.root / "snapshot/state.json").write_text('{"position": "changed"}')
    elif change == "file":
        with open(refs[1]["path"], "a") as stream:
            stream.write(" ")
    else:
        record = next(
            e
            for e in records
            if e["kind"] == "finished"
            and e["outcome"].get("checkpoint_evidence") == refs[1]
        )
        if change == "missing_ref":
            del record["outcome"]["checkpoint_evidence"]
        else:
            path = pilot.root / "tampered.json"
            data = json.loads(open(refs[1]["path"]).read())
            key, value = {
                "wrong_snapshot": ("snapshot_sha256", "b" * 64),
                "wrong_protocol": ("protocol_sha256", "b" * 64),
                "wrong_capture": ("capture_report_sha256", "b" * 64),
                "wrong_attempt": ("attempt_id", "wrong"),
                "false_pass": ("passed", False),
                "empty_checks": ("checks", []),
                "failed_check": (
                    "checks",
                    [{"name": "physical state", "passed": False}],
                ),
            }[change]
            data[key] = value
            path.write_text(json.dumps(data))
            record["outcome"]["checkpoint_evidence"] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    with pytest.raises(ValueError, match="checkpoint qualification"):
        verify_qualification(pilot.manifest, records)
