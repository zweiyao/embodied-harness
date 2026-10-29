# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Append a bounded checkpoint qualification after the first failed pair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rpent.evaluation.result import write_json_atomic

from . import _verify_refs, amended_manifest, digest

CELLS = ("infra-03", "infra-04")


def revised_manifest(protocol: dict) -> dict:
    """Replace only unused repair slots, preserving the approved 40-run limit."""
    if (
        protocol.get("schema_version") != 1
        or protocol.get("name") != "univtac-checkpoint-qualification"
        or protocol.get("snapshot_schema_version") != 2
        or protocol.get("cells") != list(CELLS)
        or protocol.get("task") != "insert_hole"
        or protocol.get("seed") != 2
    ):
        raise ValueError("checkpoint protocol identity or scope differs")
    manifest = amended_manifest()
    manifest["schema_version"] = 3
    manifest["checkpoint_qualification"] = {
        "protocol_sha256": digest(protocol),
        "cells": list(CELLS),
    }
    for index, cell in enumerate(manifest["cells"]):
        if cell["id"] in ("repair-01", "repair-02"):
            manifest["cells"][index] = {
                "id": CELLS[int(cell["id"][-2:]) - 1],
                "stage": "infrastructure",
                "model": "script",
                "condition": "C",
                "task": "insert_hole",
                "seed": 2,
            }
    return manifest


def _check_timing(events: list[dict]) -> None:
    if any(e["kind"] == "frozen" for e in events):
        raise ValueError("checkpoint amendment must precede freezing")
    attempts = [e for e in events if e["kind"] == "reserved"]
    finished = {e["id"]: e for e in events if e["kind"] == "finished"}
    if any(e["id"] not in finished for e in attempts):
        raise ValueError("finish the active attempt before checkpoint amendment")
    cells = {c["id"]: c for c in amended_manifest()["cells"]}
    for attempt in attempts:
        cell = cells.get(attempt["cell"])
        if cell is None or cell.get("optional") or cell["stage"] == "holdout":
            raise ValueError(
                "checkpoint amendment cannot replace used repair or holdout cells"
            )
    old = [a for a in attempts if a["cell"] in ("infra-01", "infra-02")]
    if len(old) != 2 or all(
        finished[a["id"]]["outcome"].get("checkpoint_validation_passed") is True
        for a in old
    ):
        raise ValueError("checkpoint amendment requires the completed failed pair")


def apply_amendment(root: Path, events: list[dict], manifest: dict) -> dict:
    """Verify the append-only protocol and retain prior failed attempts."""
    amendments = [e for e in events if e["kind"] == "checkpoint_amendment"]
    if not amendments:
        return manifest
    if manifest != amended_manifest() or len(amendments) != 1:
        raise ValueError("one checkpoint amendment requires budget protocol v2")
    event = amendments[0]
    version = event.get("id", "")
    if len(version) != 64 or any(c not in "0123456789abcdef" for c in version):
        raise ValueError("invalid checkpoint amendment id")
    payload = json.loads((root / f"checkpoint-amendment-{version}.json").read_text())
    prior = events[: events.index(event)]
    allocation = next((e for e in prior if e["kind"] == "budget_amendment"), None)
    if (
        digest(payload) != version
        or set(payload) != {"budget_amendment_id", "manifest", "protocol", "reason"}
        or allocation is None
        or payload["budget_amendment_id"] != allocation["id"]
        or payload["manifest"] != revised_manifest(payload["protocol"])
        or not isinstance(payload["reason"], str)
        or not payload["reason"].strip()
        or event.get("reason") != payload["reason"]
    ):
        raise ValueError("checkpoint amendment evidence differs")
    _check_timing(prior)
    return payload["manifest"]


def amendment_operation(pilot, events: list[dict], protocol: dict, reason: str):
    """Prepare one locked ledger append with an immutable protocol payload."""
    if pilot.manifest != amended_manifest():
        raise ValueError("checkpoint amendment requires unamended budget protocol v2")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("provide the checkpoint revision reason")
    _check_timing(events)
    allocation = next(e for e in events if e["kind"] == "budget_amendment")
    payload = {
        "budget_amendment_id": allocation["id"],
        "manifest": revised_manifest(protocol),
        "protocol": protocol,
        "reason": reason.strip(),
    }
    version = digest(payload)
    path = pilot.root / f"checkpoint-amendment-{version}.json"
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise ValueError("immutable checkpoint amendment differs")
    else:
        write_json_atomic(path, payload)
    return version, {
        "kind": "checkpoint_amendment",
        "id": version,
        "reason": payload["reason"],
    }


def verify_qualification(manifest: dict, events: list[dict]) -> None:
    """Require bound capture/restore evidence, rather than a success boolean."""
    qualification = manifest["checkpoint_qualification"]
    reports, refs = [], []
    for cell_id, role in zip(CELLS, ("capture", "restore"), strict=True):
        attempt = next(
            e for e in events if e["kind"] == "reserved" and e["cell"] == cell_id
        )
        outcome = next(
            e["outcome"]
            for e in events
            if e["kind"] == "finished" and e["id"] == attempt["id"]
        )
        ref = outcome.get("checkpoint_evidence")
        if not isinstance(ref, dict) or not {"path", "sha256"} <= ref.keys():
            raise ValueError("checkpoint qualification evidence missing")
        report = _read_evidence(ref)
        snapshot = report.get("snapshot_sha256", "")
        if (
            report.get("passed") is not True
            or report.get("protocol_sha256") != qualification["protocol_sha256"]
            or report.get("attempt_id") != attempt["id"]
            or report.get("role") != role
            or report.get("cell_id") != cell_id
            or not isinstance(snapshot, str)
            or len(snapshot) != 64
            or any(c not in "0123456789abcdef" for c in snapshot)
        ):
            raise ValueError(
                "checkpoint qualification report does not match the frozen protocol"
            )
        checks = report.get("checks")
        if (
            not isinstance(checks, list)
            or not checks
            or any(
                not isinstance(check, dict) or check.get("passed") is not True
                for check in checks
            )
        ):
            raise ValueError("checkpoint qualification checks are missing or failed")
        saved = _read_evidence(report.get("snapshot_manifest"))
        root = Path(report["snapshot_manifest"]["path"]).resolve().parent
        files = saved.get("files", {})
        if (
            saved.get("schema_version") != 2
            or digest(saved) != snapshot
            or not {"state.json", "scene.json", "baseline.json", "protocol.json"}
            <= files.keys()
            or len([name for name in files if name.startswith("dump/")]) != 9
        ):
            raise ValueError("checkpoint qualification snapshot is incomplete")
        file_refs = {}
        for name, sha in files.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                raise ValueError("checkpoint qualification file leaves snapshot root")
            file_refs[name] = {"path": str(path), "sha256": sha}
        _verify_refs(file_refs, label="checkpoint qualification snapshot")
        if (
            digest(_read_evidence(file_refs["protocol.json"]))
            != qualification["protocol_sha256"]
        ):
            raise ValueError("checkpoint qualification snapshot protocol differs")
        branch = _read_evidence(report.get("branch_evidence"))
        try:
            measurements = [branch["anchor"], *branch["stationary"]] + [
                step["scene"] for step in branch["steps"]
            ]
            native_refs = {
                str(index): measurement["native"]
                for index, measurement in enumerate(measurements)
            }
        except (KeyError, TypeError) as exc:
            raise ValueError(
                "checkpoint qualification branch measurements missing"
            ) from exc
        _verify_refs(native_refs, label="checkpoint qualification native observations")
        capture_id = attempt["id"] if role == "capture" else reports[0]["attempt_id"]
        if saved.get("capture_attempt_id") != capture_id:
            raise ValueError(
                "checkpoint qualification snapshot belongs to another attempt"
            )
        reports.append(report)
        refs.append(ref)
    if (
        reports[0]["snapshot_sha256"] != reports[1]["snapshot_sha256"]
        or reports[1].get("capture_report_sha256") != refs[0]["sha256"]
    ):
        raise ValueError("checkpoint qualification pair references different evidence")


def _read_evidence(ref: dict | None) -> dict:
    if not isinstance(ref, dict) or not {"path", "sha256"} <= ref.keys():
        raise ValueError("checkpoint qualification evidence reference missing")
    try:
        data = Path(ref["path"]).read_bytes()
    except OSError as exc:
        raise ValueError("checkpoint qualification evidence is unavailable") from exc
    if hashlib.sha256(data).hexdigest() != ref["sha256"]:
        raise ValueError("checkpoint qualification evidence changed")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("checkpoint qualification evidence must be an object")
    return value
