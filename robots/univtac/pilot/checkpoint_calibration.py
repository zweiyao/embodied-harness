# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Calibrate image noise on infra-03, then independently test infra-04 once.

The original capture remains failed under v1. This module never edits its report,
snapshot, source or protocol, and never changes a non-RGB comparison criterion.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from debug import univtac_checkpoint_check as v1
from debug import univtac_checkpoint_compare as comparison
from rpent.evaluation.result import write_json_atomic

from . import Pilot, _verify_refs, digest
from .checkpoint_protocol import _read_evidence

NAME = "univtac-checkpoint-qualification-v2"
V1_SOURCES = {
    "univtac_checkpoint_check.py": "eba9ae9a3500b41004bae0aab31603d19d6431587f9ab65d60bd2330cab47d13",
    "univtac_checkpoint_compare.py": "4c8ae6556fee303b63bd8e77cf72524add7e7c3a1b7f41b69f9fe2d2b64120ef",
}
V1_PROTOCOL = "0630ef571c1accbc1f2901a264312533c090f9b407405c87c3ea2d6243ce8663"
RGB_INPUTS = tuple(key for key in comparison.RGB_KEYS if not key.endswith("rgb_marker"))
NOISE_FAILURES = {
    "capture/static_noise/observation/head/rgb",
    "capture/static_noise/tactile/left_tactile/rgb_marker",
    "capture/static_noise/tactile/right_tactile/rgb_marker",
}
LABELS = tuple(f"stationary{i}" for i in range(4)) + tuple(
    f"command{i}" for i in range(1, 4)
)


def reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": comparison.file_hash(path)}


def sources():
    return {
        **{
            name: comparison.file_hash(Path(v1.__file__).with_name(name))
            for name in V1_SOURCES
        },
        "checkpoint_calibration.py": comparison.file_hash(__file__),
    }


def _timing(events):
    attempts = [e for e in events if e["kind"] == "reserved"]
    finished = Pilot._finished(events)
    if any(e["kind"] == "frozen" for e in events) or any(
        e["id"] not in finished for e in attempts
    ):
        raise ValueError("Calibration must precede freezing and have no active attempt")
    if any(
        e["cell"] == "infra-04"
        or e["cell"].startswith(("qwen3.8-max-", "gpt-6-astra-"))
        for e in attempts
    ):
        raise ValueError(
            "Calibration must precede infra-04 and every holdout reservation"
        )
    capture = next((e for e in attempts if e["cell"] == "infra-03"), None)
    if capture is None or capture["id"] not in finished:
        raise ValueError("Completed infra-03 calibration capture required")
    return capture, finished[capture["id"]]


def capture_evidence(events):
    """Accept only the intact v1 capture with precisely the three known failures."""
    capture = next(
        e for e in events if e["kind"] == "reserved" and e["cell"] == "infra-03"
    )
    outcome = Pilot._finished(events)[capture["id"]]["outcome"]
    ref = outcome["checkpoint_evidence"]
    report = _read_evidence(ref)
    checks = report.get("checks", [])
    failed = [c for c in checks if c.get("passed") is False]
    if (
        outcome.get("checkpoint_validation_passed") is not False
        or report.get("passed") is not False
        or report.get("role") != "capture"
        or report.get("cell_id") != "infra-03"
        or report.get("attempt_id") != capture["id"]
        or report.get("protocol_sha256") != V1_PROTOCOL
        or len(checks) != 430
        or len({c["name"] for c in checks}) != 430
        or {c["name"] for c in failed} != NOISE_FAILURES
        or sum(c.get("passed") is True for c in checks) != 427
    ):
        raise ValueError(
            "Capture must retain 427 passes and only the three v1 image-noise failures"
        )
    manifest = _read_evidence(report["snapshot_manifest"])
    root = Path(report["snapshot_manifest"]["path"]).resolve().parent
    if (
        manifest != v1.read_verified(root)
        or manifest.get("schema_version") != 2
        or manifest.get("capture_attempt_id") != capture["id"]
        or manifest.get("source_sha256") != V1_SOURCES
        or digest(manifest) != report["snapshot_sha256"]
        or digest(json.loads((root / "protocol.json").read_text())) != V1_PROTOCOL
        or report["branch_evidence"] != reference(root / "baseline.json")
        or len([name for name in manifest["files"] if name.startswith("dump/")]) != 9
    ):
        raise ValueError("Capture snapshot/source/protocol binding differs")
    branch = _read_evidence(report["branch_evidence"])
    if len(branch["stationary"]) != 4 or len(branch["steps"]) != 3:
        raise ValueError("Four calibration frames and three fixed commands required")
    measurements = [branch["anchor"], *branch["stationary"]] + [
        s["scene"] for s in branch["steps"]
    ]
    native_refs = {str(i): m["native"] for i, m in enumerate(measurements)}
    for item in native_refs.values():
        path = Path(item["path"]).resolve()
        if (
            root not in path.parents
            or str(path.relative_to(root)) not in manifest["files"]
        ):
            raise ValueError("Calibration observation is outside its frozen snapshot")
    _verify_refs(native_refs, label="calibration observations")
    return (
        {
            "attempt_id": capture["id"],
            "report": ref,
            "snapshot_manifest": report["snapshot_manifest"],
            "snapshot_sha256": digest(manifest),
            "branch": report["branch_evidence"],
            "native_observations": native_refs,
            "v1_failed_checks": failed,
            "v1_passed_checks": 427,
            "v1_total_checks": 430,
            "original_capture_passed": False,
        },
        branch,
        root,
    )


def prepare(events):
    """Freeze thresholds from development images, without touching the ledger."""
    import itertools

    _timing(events)
    evidence, branch, root = capture_evidence(events)
    current = sources()
    if (
        any(current[name] != sha for name, sha in V1_SOURCES.items())
        or digest(comparison.protocol()) != V1_PROTOCOL
    ):
        raise ValueError("The v1 diagnostic source/protocol must remain byte-identical")
    frames = [
        comparison.native(m, root, comparison.protocol()) for m in branch["stationary"]
    ]
    limits = {
        key: (
            np.max(
                [
                    comparison._tiles(a[key].astype(float), b[key].astype(float), 32)
                    for a, b in itertools.combinations(frames, 2)
                ],
                axis=0,
            )
            + 1.0
        ).tolist()
        for key in RGB_INPUTS
    }
    return {
        "schema_version": 2,
        "name": NAME,
        "snapshot_schema_version": 2,
        "calibration_cell": "infra-03",
        "acceptance_cell": "infra-04",
        "task": "insert_hole",
        "seed": 2,
        "parent_protocol_sha256": V1_PROTOCOL,
        "calibration": evidence,
        "source_sha256": current,
        "rgb_inputs": list(RGB_INPUTS),
        "excluded_display_only": [
            k for k in comparison.RGB_KEYS if k not in RGB_INPUTS
        ],
        "rgb_tile_size_px": 32,
        "rgb_margin_lsb": 1.0,
        "rgb_limits_global_then_row_major_tiles": limits,
        "rule": "Each RGB global/tile RMSE <= maximum of the six captured static pair RMSEs + 1 LSB; no pooled score or later tuning. All non-RGB v1 checks remain unchanged.",
        "limitation": "Four development frames calibrate engineering tolerance, not a statistical confidence bound. Infra-03 remains failed under v1; only the independent infra-04 restore can qualify under v2.",
    }


def _v4(manifest, protocol):
    result = copy.deepcopy(manifest)
    result["schema_version"] = 4
    result["checkpoint_qualification"] = {
        "protocol_sha256": digest(protocol),
        "cells": ["infra-03", "infra-04"],
        "calibration_report": protocol["calibration"]["report"],
        "acceptance_cell": "infra-04",
    }
    return result


def apply_calibration(root, events, manifest):
    """Load one append-only calibration amendment after unchanged v3 history."""
    records = [e for e in events if e["kind"] == "checkpoint_calibration"]
    if not records:
        return manifest
    if len(records) != 1 or manifest.get("schema_version") != 3:
        raise ValueError("One calibration amendment requires protocol v3")
    event = records[0]
    version = event["id"]
    if (
        not isinstance(version, str)
        or len(version) != 64
        or any(c not in "0123456789abcdef" for c in version)
    ):
        raise ValueError("Invalid calibration amendment id")
    payload = json.loads((root / f"checkpoint-calibration-{version}.json").read_text())
    prior = events[: events.index(event)]
    _timing(prior)
    if (
        digest(payload) != version
        or set(payload) != {"parent_manifest_sha256", "protocol", "manifest", "reason"}
        or payload["parent_manifest_sha256"] != digest(manifest)
        or payload["manifest"] != _v4(manifest, payload["protocol"])
        or payload["protocol"].get("name") != NAME
        or payload["reason"] != event.get("reason")
        or not payload["reason"]
    ):
        raise ValueError("Calibration amendment differs from its immutable payload")
    return payload["manifest"]


def register(pilot, protocol, reason):
    def operation(events):
        if pilot.manifest.get("schema_version") != 3 or not reason.strip():
            raise ValueError("Calibration needs unamended v3 and an explicit reason")
        if protocol != prepare(events):
            raise ValueError(
                "Calibration protocol does not match immutable capture and current runner"
            )
        payload = {
            "parent_manifest_sha256": digest(pilot.manifest),
            "protocol": protocol,
            "manifest": _v4(pilot.manifest, protocol),
            "reason": reason.strip(),
        }
        version = digest(payload)
        path = pilot.root / f"checkpoint-calibration-{version}.json"
        if path.exists() and json.loads(path.read_text()) != payload:
            raise ValueError("Immutable calibration payload changed")
        if not path.exists():
            write_json_atomic(path, payload)
        return version, {
            "kind": "checkpoint_calibration",
            "id": version,
            "reason": reason.strip(),
        }

    return pilot._transaction(operation)


def registered(root, events, manifest):
    event = next(e for e in events if e["kind"] == "checkpoint_calibration")
    payload = json.loads(
        (Path(root) / f"checkpoint-calibration-{event['id']}.json").read_text()
    )
    protocol = payload["protocol"]
    if (
        digest(payload) != event["id"]
        or digest(protocol) != manifest["checkpoint_qualification"]["protocol_sha256"]
    ):
        raise ValueError("Registered calibration protocol changed")
    # Recompute only at execution/freeze boundaries, never on every ledger read.
    if protocol != prepare(events[: events.index(event)]):
        raise ValueError("Calibration sources or evidence changed after registration")
    return protocol


def compare(protocol, baseline, actual, snapshot, output):
    """Replace only declared RGB checks and retain the complete v1 result."""
    old = comparison.compare_branches(baseline, actual, snapshot, output)
    checks, excluded = [], []
    for item in old["checks"]:
        name = item["name"]
        if name in {
            "capture/static_noise/" + k for k in comparison.RGB_KEYS
        } or name in {
            label + "/" + k
            for label in LABELS
            for k in protocol["excluded_display_only"]
        }:
            excluded.append(item)
        elif name not in {label + "/" + k for label in LABELS for k in RGB_INPUTS}:
            checks.append(item)
    try:
        pairs = list(zip(baseline["stationary"], actual["stationary"])) + [
            (a["scene"], b["scene"]) for a, b in zip(baseline["steps"], actual["steps"])
        ]
        if len(pairs) != len(LABELS) or len(old["checks"]) != 430:
            raise ValueError(
                "Incomplete original comparison; no omitted check may pass"
            )
        for label, (a, b) in zip(LABELS, pairs):
            aa, bb = (
                comparison.native(a, snapshot, comparison.protocol()),
                comparison.native(b, output, comparison.protocol()),
            )
            for key in RGB_INPUTS:
                error = comparison._tiles(
                    aa[key].astype(float), bb[key].astype(float), 32
                )
                limits = np.asarray(
                    protocol["rgb_limits_global_then_row_major_tiles"][key]
                )
                if error.shape != limits.shape or not np.isfinite(error).all():
                    raise ValueError("RGB calibration shape/value mismatch")
                comparison.add(
                    checks,
                    label + "/" + key,
                    np.all(error <= limits),
                    global_rmse=float(error[0]),
                    max_tile_rmse=float(error[1:].max()),
                    rejected_tiles=int(np.sum(error[1:] > limits[1:])),
                    maximum_allowed=float(limits.max()),
                )
    except (KeyError, OSError, ValueError, TypeError) as exc:
        comparison.add(checks, "calibration_required_evidence", False, error=str(exc))
    return {
        "passed": bool(checks) and all(c["passed"] for c in checks),
        "checks": checks,
        "excluded_display_or_calibration_checks": excluded,
        "original_v1": old,
    }


def write_report(protocol, output, attempt_id, result):
    """Write a fresh restore report; never update the original capture report."""
    output = Path(output)
    if (output / "report.json").exists():
        raise FileExistsError("Restore qualification report already exists")
    write_json_atomic(output / "comparison-v1.json", result["original_v1"])
    report = {
        "passed": result["passed"],
        "protocol_sha256": digest(protocol),
        "attempt_id": attempt_id,
        "cell_id": "infra-04",
        "role": "restore",
        "snapshot_sha256": protocol["calibration"]["snapshot_sha256"],
        "calibration": protocol["calibration"],
        "source_sha256": protocol["source_sha256"],
        "checks": result["checks"],
        "excluded_display_or_calibration_checks": result[
            "excluded_display_or_calibration_checks"
        ],
        "branch_evidence": reference(output / "restored-measurements.json"),
        "original_v1_result": reference(output / "comparison-v1.json"),
    }
    write_json_atomic(output / "report.json", report)
    return reference(output / "report.json")


def verify_qualification(root, manifest, events):
    protocol = registered(root, events, manifest)
    attempt = next(
        e for e in events if e["kind"] == "reserved" and e["cell"] == "infra-04"
    )
    outcome = Pilot._finished(events)[attempt["id"]]["outcome"]
    report = _read_evidence(outcome.get("checkpoint_evidence"))
    if (
        outcome.get("checkpoint_validation_passed") is not True
        or outcome.get("termination_reason") != "completed"
        or report.get("passed") is not True
        or report.get("role") != "restore"
        or report.get("cell_id") != "infra-04"
        or report.get("attempt_id") != attempt["id"]
        or report.get("protocol_sha256") != digest(protocol)
        or report.get("snapshot_sha256") != protocol["calibration"]["snapshot_sha256"]
        or report.get("calibration") != protocol["calibration"]
        or report.get("source_sha256") != sources()
    ):
        raise ValueError("Independent calibrated restore has not qualified")
    actual = _read_evidence(report["branch_evidence"])
    snapshot = Path(protocol["calibration"]["snapshot_manifest"]["path"]).parent
    baseline = _read_evidence(protocol["calibration"]["branch"])
    computed = compare(
        protocol,
        baseline,
        actual,
        snapshot,
        Path(report["branch_evidence"]["path"]).parent,
    )
    if (
        not computed["passed"]
        or computed["checks"] != report.get("checks")
        or computed["excluded_display_or_calibration_checks"]
        != report.get("excluded_display_or_calibration_checks")
        or computed["original_v1"] != _read_evidence(report["original_v1_result"])
    ):
        raise ValueError("Restore report omitted or changed a required comparison")


def run(args):
    """Use the immutable v1 restoration engine, with no new capture or retries."""
    from robots.univtac.backend import UniVTACBackend

    pilot, output = Pilot(args.pilot_root), Path(args.output_dir).resolve()

    def preflight(events):
        protocol = registered(pilot.root, events, pilot.manifest)
        attempt = pilot._attempt(events, args.attempt_id)
        if (
            attempt["cell"] != "infra-04"
            or args.attempt_id in pilot._finished(events)
            or Path(attempt["session_id"]).resolve() != output
        ):
            raise ValueError("Fresh charged infra-04 reservation required")
        return protocol, None

    protocol = pilot._transaction(preflight)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "checkpoint-started.json").open("x") as stream:
        json.dump(
            {"attempt_id": args.attempt_id, "protocol_sha256": digest(protocol)}, stream
        )
    snapshot = Path(protocol["calibration"]["snapshot_manifest"]["path"]).parent
    result = {
        "checkpoint_validation_passed": False,
        "official_success": None,
        "native_success": None,
        "protocol_sha256": digest(protocol),
        "initializations": 0,
        "status": "running",
        "controller_changed": False,
        "renderer_cache_restored": False,
    }
    backend, started = None, time.monotonic()
    write_json_atomic(output / "protocol.json", protocol)
    try:
        backend = UniVTACBackend(root=args.root, output_dir=output / "native", seed=2)
        result["initializations"] = 1
        write_json_atomic(output / "checkpoint-result.json", result)
        backend.reset()
        pilot.record_scene(args.attempt_id, backend.evaluator_state()["scene"])
        result["status"] = "initialized"
        v1.restore(backend, snapshot)
        baseline = _read_evidence(protocol["calibration"]["branch"])
        backend.task._rpent_archive = output / "restored-native-frames"
        actual = {
            "anchor": v1.measure(backend),
            "stationary": v1.stationary_samples(backend),
            "actions": baseline["actions"],
            "steps": v1.short_branch(backend, baseline["actions"]),
        }
        write_json_atomic(output / "restored-measurements.json", actual)
        compared = compare(protocol, baseline, actual, snapshot, output)
        result["checkpoint_evidence"] = write_report(
            protocol, output, args.attempt_id, compared
        )
        result["checkpoint_validation_passed"] = compared["passed"]
        result["status"] = "passed" if compared["passed"] else "failed"
        result["termination_reason"] = "completed" if compared["passed"] else "failed"
        result["official_success"] = backend.evaluator_state()["official_success"]
        result["native_success"] = result["official_success"]
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["termination_reason"] = (
            "aborted"
            if isinstance(exc, KeyboardInterrupt)
            else "setup_failure"
            if result["status"] == "running"
            else "failed"
        )
        result["status"] = "failed"
        details = traceback.format_exc()
        (output / "checkpoint-error.txt").write_text(details)
        sys.stderr.write(details)
        sys.stderr.flush()
    finally:
        result["elapsed_s"] = time.monotonic() - started
        write_json_atomic(output / "checkpoint-result.json", result)
        try:
            pilot.finish_episode(args.attempt_id, result)
        finally:
            if backend is not None:
                backend.close()
    return 0 if result["checkpoint_validation_passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "register", "run"):
        p = sub.add_parser(name)
        p.add_argument("--pilot-root", type=Path, required=True)
        if name == "prepare":
            p.add_argument("--output", type=Path, required=True)
        elif name == "register":
            p.add_argument("--protocol", type=Path, required=True)
            p.add_argument("--reason", required=True)
        else:
            p.add_argument("--attempt-id", required=True)
            p.add_argument("--root", required=True)
            p.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.command == "run":
        raise SystemExit(run(args))
    pilot = Pilot(args.pilot_root)
    if args.command == "prepare":
        value = pilot._transaction(lambda events: (prepare(events), None))
        if args.output.exists():
            raise FileExistsError("Prepared protocol already exists")
        write_json_atomic(args.output, value)
        print(json.dumps({"path": str(args.output), "protocol_sha256": digest(value)}))
    else:
        print(register(pilot, json.loads(args.protocol.read_text()), args.reason))


if __name__ == "__main__":
    main()
