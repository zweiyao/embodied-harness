# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Real calibration producer/consumer contracts, using numeric CPU evidence."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from debug import univtac_checkpoint_check as v1
from debug import univtac_checkpoint_compare as comparator
from robots.univtac.pilot import Pilot
from robots.univtac.pilot import checkpoint_calibration as calibration
from tests.unit_tests.robots.univtac import (
    test_checkpoint_compare as comparison_fixtures,
)

branch = comparison_fixtures.branch


def events(pilot):
    return [
        json.loads(line)
        for line in (pilot.root / "events.jsonl").read_text().splitlines()
    ]


def measurements(branch):
    return [
        branch["anchor"],
        *branch["stationary"],
        *[step["scene"] for step in branch["steps"]],
    ]


@pytest.fixture
def calibrated(tmp_path, branch):
    # insert_hole records the slot, prism base and held prism. Keep the same
    # inventory so the real comparator emits the complete 430-check report.
    for item in measurements(branch):
        actors = item["scene"]["state"]["actors"]
        actors["slot"] = list(actors["prism"])
        actors["prism_base"] = list(actors["prism"])
    pilot = Pilot.create(tmp_path / "pilot")
    pilot.amend_budget("approved 12/24/4")
    for cell in ("infra-01", "infra-02"):
        attempt = pilot.reserve_episode(cell, cell)
        pilot.finish_episode(
            attempt,
            {"termination_reason": "failed", "checkpoint_validation_passed": False},
        )
    pilot.amend_checkpoint_validation(comparator.protocol(), "fixed targets")
    output, snapshot = pilot.root / "capture", pilot.root / "snapshot"
    output.mkdir()
    snapshot.mkdir()
    attempt = pilot.reserve_episode("infra-03", str(output))
    pilot.record_scene(attempt, branch["anchor"]["scene"])
    frame = snapshot / "anchor.npz"
    frame.write_bytes((tmp_path / "native.npz").read_bytes())
    for item in measurements(branch):
        item["native"] = calibration.reference(frame)
    for index, item in enumerate(branch["stationary"]):
        with np.load(frame, allow_pickle=False) as archive:
            arrays = dict(archive)
        arrays["observation/head/rgb"] += index * 4
        for side in ("left", "right"):
            arrays[f"tactile/{side}_tactile/rgb_marker"] += index * 8
        saved = snapshot / f"static-{index}.npz"
        np.savez_compressed(saved, **arrays)
        item["native"] = calibration.reference(saved)
    for name, payload in (
        ("state", {}),
        ("scene", {}),
        ("baseline", branch),
        ("protocol", comparator.protocol()),
    ):
        (snapshot / f"{name}.json").write_text(json.dumps(payload))
    (snapshot / "dump").mkdir()
    for index in range(9):
        (snapshot / "dump" / str(index)).write_bytes(b"UIPC fixture buffer")
    manifest = {
        "schema_version": 2,
        "task": "insert_hole",
        "seed": 2,
        "frame": 100,
        "capture_attempt_id": attempt,
        "source_sha256": calibration.V1_SOURCES,
        "files": {
            str(p.relative_to(snapshot)): comparator.file_hash(p)
            for p in snapshot.rglob("*")
            if p.is_file()
        },
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    checked = comparator.compare_branches(branch, branch, snapshot, snapshot)
    assert len(checked["checks"]) == 430
    assert {
        c["name"] for c in checked["checks"] if not c["passed"]
    } == calibration.NOISE_FAILURES
    evidence = v1.qualification_report(output, snapshot, attempt, "capture", checked)
    pilot.finish_episode(
        attempt,
        {
            "termination_reason": "failed",
            "checkpoint_validation_passed": False,
            "checkpoint_evidence": evidence,
        },
    )
    protocol = calibration.prepare(events(pilot))
    return pilot, snapshot, branch, protocol


def restored(calibrated):
    pilot, snapshot, baseline, protocol = calibrated
    pilot.amend_checkpoint_calibration(
        protocol, "developer noise calibration; original failure retained"
    )
    output = pilot.root / "restore"
    output.mkdir()
    attempt = pilot.reserve_episode("infra-04", str(output))
    pilot.record_scene(attempt, baseline["anchor"]["scene"])
    actual = copy.deepcopy(baseline)
    for index, item in enumerate(measurements(actual)):
        source = Path(item["native"]["path"])
        destination = output / f"native-{index}.npz"
        destination.write_bytes(source.read_bytes())
        item["native"] = calibration.reference(destination)
    return pilot, snapshot, baseline, protocol, output, attempt, actual


def finish_restore(values, comparison=None):
    pilot, snapshot, baseline, protocol, output, attempt, actual = values
    (output / "restored-measurements.json").write_text(json.dumps(actual))
    compared = comparison or calibration.compare(
        protocol, baseline, actual, snapshot, output
    )
    ref = calibration.write_report(protocol, output, attempt, compared)
    pilot.finish_episode(
        attempt,
        {
            "termination_reason": "completed" if compared["passed"] else "failed",
            "checkpoint_validation_passed": compared["passed"],
            "checkpoint_evidence": ref,
        },
    )
    return ref, compared


def test_calibrated_producer_to_gate_preserves_failed_capture_and_budget(calibrated):
    pilot, snapshot, _, protocol = calibrated
    old_ledger = (pilot.root / "events.jsonl").read_bytes()
    old_files = {p: p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
    values = restored(calibrated)
    ref, checked = finish_restore(values)
    assert checked["passed"] and checked["original_v1"]["passed"] is False
    assert (
        protocol["rgb_limits_global_then_row_major_tiles"]["observation/head/rgb"][0]
        == 13
    )
    assert (
        protocol["rgb_limits_global_then_row_major_tiles"]["tactile/left_tactile/rgb"][
            0
        ]
        == 1
    )
    assert all("rgb_marker" not in c["name"] for c in checked["checks"])
    calibration.verify_qualification(pilot.root, pilot.manifest, events(pilot))
    reopened = Pilot(pilot.root)
    assert (
        reopened.manifest["schema_version"] == 4
        and len(reopened.manifest["cells"]) == 40
    )
    assert reopened.summary()["development_limit"] == 12
    assert reopened.summary()["holdout_limits"] == {"qwen3.8-max": 24, "gpt-6-astra": 4}
    assert (pilot.root / "events.jsonl").read_bytes().startswith(old_ledger)
    assert all(path.read_bytes() == data for path, data in old_files.items())
    assert (
        json.loads(Path(protocol["calibration"]["report"]["path"]).read_text())[
            "passed"
        ]
        is False
    )
    report = json.loads(Path(ref["path"]).read_text())
    assert report["calibration"]["original_capture_passed"] is False


@pytest.mark.parametrize(
    "changed", ["margin", "omitted_limit", "native_file", "source"]
)
def test_registration_rejects_unbound_calibration(calibrated, changed):
    pilot, _, _, protocol = calibrated
    if changed == "margin":
        protocol["rgb_limits_global_then_row_major_tiles"]["observation/head/rgb"][
            0
        ] += 1
    elif changed == "omitted_limit":
        del protocol["rgb_limits_global_then_row_major_tiles"]["observation/head/rgb"]
    elif changed == "source":
        protocol["source_sha256"]["checkpoint_calibration.py"] = "wrong"
    else:
        Path(protocol["calibration"]["native_observations"]["0"]["path"]).write_bytes(
            b"changed"
        )
    prefix = (pilot.root / "events.jsonl").read_bytes()
    with pytest.raises(ValueError):
        pilot.amend_checkpoint_calibration(protocol, "test")
    assert (pilot.root / "events.jsonl").read_bytes() == prefix


@pytest.mark.parametrize(
    "changed",
    ["target", "missing_marker", "tile_outside_envelope", "omitted_failed_check"],
)
def test_non_rgb_failures_and_local_rgb_changes_cannot_be_hidden(calibrated, changed):
    values = restored(calibrated)
    pilot, snapshot, baseline, protocol, output, _, actual = values
    if changed in ("target", "omitted_failed_check"):
        actual["anchor"]["joint_targets"]["joint_vel_target"]["data"][0][0] = 1e-8
    else:
        item = actual["stationary"][0]
        path = Path(item["native"]["path"])
        with np.load(path, allow_pickle=False) as archive:
            arrays = dict(archive)
        if changed == "missing_marker":
            del arrays["tactile/left_tactile/marker"]
        else:
            arrays["observation/head/rgb"][:32, :32] += 14
        np.savez_compressed(path, **arrays)
        item["native"] = calibration.reference(path)
    checked = calibration.compare(protocol, baseline, actual, snapshot, output)
    assert not checked["passed"]
    if changed == "omitted_failed_check":
        checked["checks"] = [c for c in checked["checks"] if c["passed"]]
        checked["passed"] = True
    finish_restore(values, checked)
    with pytest.raises(ValueError):
        calibration.verify_qualification(pilot.root, pilot.manifest, events(pilot))


def test_calibration_cannot_follow_restore_reservation(calibrated):
    pilot, _, _, protocol = calibrated
    attempt = pilot.reserve_episode("infra-04", "already-used")
    pilot.finish_episode(
        attempt, {"termination_reason": "failed", "checkpoint_validation_passed": False}
    )
    with pytest.raises(ValueError, match="precede infra-04"):
        pilot.amend_checkpoint_calibration(protocol, "too late")


def test_changed_restore_npz_rejected_after_produced_report(calibrated):
    values = restored(calibrated)
    pilot, _, _, _, _, _, actual = values
    finish_restore(values)
    Path(actual["stationary"][0]["native"]["path"]).write_bytes(b"changed after report")
    with pytest.raises(ValueError):
        calibration.verify_qualification(pilot.root, pilot.manifest, events(pilot))
