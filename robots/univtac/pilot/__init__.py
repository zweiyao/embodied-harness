# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Bounded tactile pilot accounting; execution stays in RPent's planners."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rpent.evaluation.result import write_json_atomic

SCENE_PARTS = {"model", "state", "physics", "sensors", "rng", "assets"}
TERMINATIONS = {
    "completed",
    "failed",
    "aborted",
    "timeout",
    "network_failure",
    "setup_failure",
    "scene_mismatch",
    "abnormal_exit",
    "budget_exhausted",
}


def digest(value: Any) -> str:
    """Hash a JSON value, rejecting non-finite numbers."""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def default_manifest() -> dict:
    """Return the fixed eight development and 32 held-out episode slots."""
    cells = []
    stages = [
        ("smoke", "script", "C", (0, 1)),
        ("explore", "gpt-6-astra", "C", (2, 3)),
        ("provisional", "qwen3.8-max", "provisional", (2, 3)),
        ("validate", "qwen3.8-max", "E", (4, 5)),
    ]
    for stage, model, condition, seeds in stages:
        for seed in seeds:
            cells.append(
                {
                    "id": f"dev-{len(cells) + 1:02d}",
                    "stage": stage,
                    "model": model,
                    "condition": condition,
                    "task": "insert_hole",
                    "seed": seed,
                }
            )
    for model, conditions, seeds in [
        ("qwen3.8-max", "CDEF", (100, 101, 102)),
        ("gpt-6-astra", "CE", (100, 101)),
    ]:
        for task in ("insert_tube", "pull_out_key"):
            for index, seed in enumerate(seeds):
                order = conditions[index:] + conditions[:index]
                for condition in order:
                    cells.append(
                        {
                            "id": f"{model}-{task}-{seed}-{condition}",
                            "stage": "holdout",
                            "model": model,
                            "condition": condition,
                            "task": task,
                            "seed": seed,
                        }
                    )
    return {
        "schema_version": 1,
        "max_episodes": 40,
        "max_offline_requests": 80,
        "memory_mode": "read_only",
        "cells": cells,
    }


def amended_manifest() -> dict:
    """Keep 40 slots: up to 12 development, 24 Max and four GPT holdout runs."""
    manifest = default_manifest()
    extra = [
        {
            "id": f"infra-{index:02d}",
            "stage": "infrastructure",
            "model": "script",
            "condition": "C",
            "task": "insert_hole",
            "seed": 2,
        }
        for index in (1, 2)
    ] + [
        {
            "id": f"repair-{index:02d}",
            "stage": "provisional",
            "model": "qwen3.8-max",
            "condition": "provisional",
            "task": "insert_hole",
            "seed": seed,
            "optional": True,
        }
        for index, seed in enumerate((6, 7), 1)
    ]
    manifest["schema_version"] = 2
    manifest["cells"] = (
        manifest["cells"][:8]
        + extra
        + [
            cell
            for cell in manifest["cells"][8:]
            if not (cell["model"] == "gpt-6-astra" and cell["seed"] == 101)
        ]
    )
    return manifest


def scene_fingerprint(components: dict) -> str:
    """Hash evaluator-only simulator state, configuration and asset evidence.

    Components must describe the simulator, not the tested language model.
    This verifies recorded equality; it does not establish restorability of
    unobserved soft-body state.
    """
    if not SCENE_PARTS <= components.keys() or any(
        components[key] in (None, {}, [], "") for key in SCENE_PARTS
    ):
        raise ValueError("scene needs nonempty model/state/physics/sensors/rng/assets")
    return digest(components)


def _file_refs(paths: dict) -> dict:
    refs = {}
    for name, value in paths.items():
        path = Path(value).resolve()
        refs[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return refs


def _verify_refs(refs: dict, *, label: str = "maker input") -> None:
    for ref in refs.values():
        try:
            actual = hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError(f"{label} evidence is unavailable") from exc
        if actual != ref["sha256"]:
            raise ValueError(f"{label} file changed after recording")


class Pilot:
    """Keep durable reservations, frozen conditions and evidence for one batch."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        if self.manifest != default_manifest():
            raise ValueError("pilot manifest differs from the fixed protocol")
        self._transaction(lambda events: (None, None))

    @classmethod
    def create(cls, root: str | Path) -> Pilot:
        """Create a new batch directory without replacing any existing data."""
        root = Path(root)
        root.mkdir(parents=True, exist_ok=False)
        write_json_atomic(root / "manifest.json", default_manifest())
        (root / "events.jsonl").touch()
        return cls(root)

    def _transaction(self, operation):
        import fcntl

        with (self.root / "events.jsonl").open("r+") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            file.seek(0)
            events = [json.loads(line) for line in file if line.strip()]
            self.manifest = self._manifest_for_events(events)
            result, event = operation(events)
            if event is not None:
                file.seek(0, os.SEEK_END)
                event["recorded_at"] = datetime.now(timezone.utc).isoformat()
                file.write(json.dumps(event, allow_nan=False) + "\n")
                file.flush()
                os.fsync(file.fileno())
                if event["kind"] in (
                    "budget_amendment",
                    "checkpoint_amendment",
                    "checkpoint_calibration",
                ):
                    self.manifest = self._manifest_for_events(events + [event])
            return result

    @staticmethod
    def _check_amendment_timing(events: list[dict]) -> None:
        if any(e["kind"] == "frozen" for e in events):
            raise ValueError("budget amendment must precede freezing")
        attempts = [e for e in events if e["kind"] == "reserved"]
        if any(e["id"] not in Pilot._finished(events) for e in attempts):
            raise ValueError("finish the active attempt before amending the budget")
        stages = {cell["id"]: cell["stage"] for cell in default_manifest()["cells"]}
        if any(e["cell"] not in stages for e in attempts):
            raise ValueError("budget amendment cannot change already used cells")
        if any(stages.get(e["cell"]) == "holdout" for e in attempts):
            raise ValueError("budget amendment cannot follow a used holdout cell")

    def _manifest_for_events(self, events: list[dict]) -> dict:
        from .checkpoint_calibration import apply_calibration
        from .checkpoint_protocol import apply_amendment

        amendments = [e for e in events if e["kind"] == "budget_amendment"]
        if not amendments:
            return apply_calibration(
                self.root,
                events,
                apply_amendment(self.root, events, default_manifest()),
            )
        if len(amendments) != 1:
            raise ValueError("only one budget amendment is allowed")
        event = amendments[0]
        version = event.get("id", "")
        if (
            not isinstance(version, str)
            or len(version) != 64
            or any(c not in "0123456789abcdef" for c in version)
        ):
            raise ValueError("invalid budget amendment id")
        payload = json.loads(
            (self.root / f"manifest-amendment-{version}.json").read_text()
        )
        if digest(payload) != version:
            raise ValueError("budget amendment hash mismatch")
        if (
            set(payload) != {"original_manifest_sha256", "manifest", "reason"}
            or payload["original_manifest_sha256"] != digest(default_manifest())
            or payload["manifest"] != amended_manifest()
            or not isinstance(payload["reason"], str)
            or not payload["reason"].strip()
            or event.get("reason") != payload["reason"]
        ):
            raise ValueError("budget amendment differs from the authorized protocol")
        self._check_amendment_timing(events[: events.index(event)])
        return apply_calibration(
            self.root, events, apply_amendment(self.root, events, payload["manifest"])
        )

    def amend_budget(self, reason: str) -> str:
        """Append the approved v2 allocation without rewriting original records."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("provide the user authorization reason")
        payload = {
            "original_manifest_sha256": digest(default_manifest()),
            "manifest": amended_manifest(),
            "reason": reason.strip(),
        }
        version = digest(payload)

        def amend(events):
            if any(e["kind"] == "budget_amendment" for e in events):
                raise ValueError("budget has already been amended")
            self._check_amendment_timing(events)
            path = self.root / f"manifest-amendment-{version}.json"
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("x") as file:
                    json.dump(payload, file, indent=2, allow_nan=False)
                    file.flush()
                    os.fsync(file.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if json.loads(path.read_text()) != payload:
                        raise ValueError("immutable budget amendment file differs")
                directory = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                temporary.unlink(missing_ok=True)
            return version, {
                "kind": "budget_amendment",
                "id": version,
                "reason": payload["reason"],
            }

        return self._transaction(amend)

    def amend_checkpoint_validation(self, protocol: dict, reason: str) -> str:
        """Use the two unused repair slots for a versioned checkpoint recheck."""
        from .checkpoint_protocol import amendment_operation

        return self._transaction(
            lambda events: amendment_operation(self, events, protocol, reason)
        )

    def amend_checkpoint_calibration(self, protocol: dict, reason: str) -> str:
        """Bind development noise calibration before the sole independent restore."""
        from .checkpoint_calibration import register

        return register(self, protocol, reason)

    def _cell(self, cell_id: str) -> dict:
        cell = next(
            (cell for cell in self.manifest["cells"] if cell["id"] == cell_id), None
        )
        if cell is None:
            raise ValueError("unknown protocol cell")
        return cell

    @staticmethod
    def _attempt(events: list[dict], attempt_id: str) -> dict:
        attempt = next(
            (e for e in events if e["kind"] == "reserved" and e["id"] == attempt_id),
            None,
        )
        if attempt is None:
            raise ValueError("unknown episode reservation")
        return attempt

    @staticmethod
    def _finished(events: list[dict]) -> dict:
        return {e["id"]: e for e in events if e["kind"] == "finished"}

    def reserve_episode(
        self,
        cell_id: str,
        session_id: str,
        freeze_id: str | None = None,
        memory_mode: str = "read_only",
    ) -> str:
        """Charge a slot before simulator startup, including failed attempts."""
        if not session_id or memory_mode != "read_only":
            raise ValueError("a fresh session and read_only memory are required")

        def reserve(events):
            cell = self._cell(cell_id)
            attempts = [e for e in events if e["kind"] == "reserved"]
            if len(attempts) >= self.manifest["max_episodes"]:
                raise ValueError("episode budget exhausted")
            if any(
                e["cell"] == cell_id or e["session_id"] == session_id for e in attempts
            ):
                raise ValueError("cell or model session has already been used")
            if any(e["id"] not in self._finished(events) for e in attempts):
                raise ValueError("finish the active attempt before reserving another")
            if cell.get("optional") and any(e["kind"] == "frozen" for e in events):
                raise ValueError("optional repair is closed after freezing")
            if cell["stage"] in ("validate", "holdout"):
                frozen = [e for e in events if e["kind"] == "frozen"]
                if not frozen or freeze_id != frozen[0]["id"]:
                    raise ValueError("a matching frozen bundle is required")
                self.load_freeze(freeze_id)
            if cell["stage"] == "holdout":
                finished = self._finished(events)
                for dev in self.manifest["cells"]:
                    if dev["stage"] == "holdout":
                        continue
                    record = next((e for e in attempts if e["cell"] == dev["id"]), None)
                    if dev.get("optional") and record is None:
                        continue
                    if record is None or record["id"] not in finished:
                        raise ValueError(
                            "all eight development attempts are required"
                            if self.manifest["schema_version"] == 1
                            else "all mandatory and reserved optional development attempts must finish"
                        )
                    if dev["stage"] == "validate":
                        validation = next(
                            (
                                e
                                for e in events
                                if e["kind"] == "interface_validation"
                                and e["id"] == record["id"]
                            ),
                            None,
                        )
                        passed = (
                            finished[record["id"]]["outcome"].get(
                                "interface_validation_passed"
                            )
                            is True
                        )
                        if validation is not None:
                            recorded_scene = next(
                                (
                                    e
                                    for e in events
                                    if e["kind"] == "scene" and e["id"] == record["id"]
                                ),
                                {},
                            )
                            if (
                                validation["freeze_id"] != freeze_id
                                or validation["scene_fingerprint"]
                                != recorded_scene.get("fingerprint")
                                or not recorded_scene.get("matched")
                            ):
                                raise ValueError(
                                    "interface validation freeze/scene mismatch"
                                )
                            _verify_refs(
                                {"interface": validation["evidence"]},
                                label="interface validation",
                            )
                            passed = validation["passed"] is True
                        if not passed:
                            raise ValueError(
                                "both final interface validations must pass"
                            )
                    smoke_setup_failure = (
                        dev["stage"] == "smoke"
                        and finished[record["id"]]["outcome"]["termination_reason"]
                        == "setup_failure"
                    )
                    if not smoke_setup_failure and not any(
                        e["kind"] == "scene" and e["id"] == record["id"] for e in events
                    ):
                        raise ValueError("development scene evidence is missing")
            attempt_id = uuid.uuid4().hex
            return attempt_id, {
                "kind": "reserved",
                "id": attempt_id,
                "cell": cell_id,
                "session_id": session_id,
                "memory_mode": memory_mode,
                "freeze_id": freeze_id,
            }

        return self._transaction(reserve)

    def record_scene(self, attempt_id: str, components: dict) -> str:
        """Record initial evidence before actions; reject mismatched holdout pairs."""
        fingerprint = scene_fingerprint(components)

        def record(events):
            attempt = self._attempt(events, attempt_id)
            if attempt_id in self._finished(events):
                raise ValueError("attempt is already finished")
            cell = self._cell(attempt["cell"])
            if any(e["kind"] == "scene" and e["id"] == attempt_id for e in events):
                raise ValueError("initial scene has already been recorded")
            matched = True
            for event in events:
                if (
                    event["kind"] != "scene"
                    or cell["stage"] != "holdout"
                    or not event["matched"]
                ):
                    continue
                other = self._cell(self._attempt(events, event["id"])["cell"])
                if (other["task"], other["seed"]) == (cell["task"], cell["seed"]):
                    if event["fingerprint"] != fingerprint:
                        matched = False
            return matched, {
                "kind": "scene",
                "id": attempt_id,
                "fingerprint": fingerprint,
                "components": components,
                "matched": matched,
            }

        if not self._transaction(record):
            raise ValueError("scene mismatch; finish as scene_mismatch without actions")
        return fingerprint

    def finish_episode(self, attempt_id: str, outcome: dict) -> None:
        """Persist a terminal result and optional sanitized maker input files."""
        if outcome.get("termination_reason") not in TERMINATIONS:
            raise ValueError("unknown termination_reason")
        if (
            outcome.get("native_success") is not None
            and type(outcome["native_success"]) is not bool
        ):
            raise ValueError("native_success must be a boolean or null")
        outcome = dict(outcome)
        paths = outcome.pop("maker_inputs", {})
        if set(paths) - {"sensors", "actions", "feedback"}:
            raise ValueError("maker_inputs only accepts sensors/actions/feedback")
        refs = _file_refs(paths)

        def finish(events):
            self._attempt(events, attempt_id)
            if attempt_id in self._finished(events):
                raise ValueError("attempt is already finished")
            if outcome["termination_reason"] == "completed" and not any(
                e["kind"] == "scene" and e["id"] == attempt_id and e["matched"]
                for e in events
            ):
                raise ValueError("completed attempts require initial scene evidence")
            return None, {
                "kind": "finished",
                "id": attempt_id,
                "outcome": outcome,
                "maker_inputs": refs,
            }

        self._transaction(finish)

    def record_interface_validation(
        self, attempt_id: str, passed: bool, evidence_path: str | Path
    ) -> None:
        """Append one human interface decision after a validation episode ends.

        This decision is independent of native task success and cannot replace
        an earlier decision. Formal reservations recheck the evidence bytes.
        """
        if type(passed) is not bool:
            raise ValueError("interface validation passed must be a boolean")

        def record(events):
            attempt = self._attempt(events, attempt_id)
            finished = self._finished(events).get(attempt_id)
            if self._cell(attempt["cell"])["stage"] != "validate" or finished is None:
                raise ValueError(
                    "interface validation requires an ended validate-stage attempt"
                )
            if "interface_validation_passed" in finished["outcome"] or any(
                e["kind"] == "interface_validation" and e["id"] == attempt_id
                for e in events
            ):
                raise ValueError("interface validation is already recorded")
            frozen = next((e for e in events if e["kind"] == "frozen"), {})
            scene = next(
                (e for e in events if e["kind"] == "scene" and e["id"] == attempt_id),
                {},
            )
            if attempt["freeze_id"] != frozen.get("id") or not scene.get("matched"):
                raise ValueError(
                    "interface validation requires matching freeze and scene evidence"
                )
            self.load_freeze(attempt["freeze_id"])
            evidence = _file_refs({"interface": evidence_path})["interface"]
            if Path(evidence["path"]).stat().st_size == 0:
                raise ValueError("interface validation evidence must not be empty")
            return None, {
                "kind": "interface_validation",
                "id": attempt_id,
                "passed": passed,
                "freeze_id": attempt["freeze_id"],
                "scene_fingerprint": scene["fingerprint"],
                "evidence": evidence,
            }

        self._transaction(record)

    def _maker_inputs(
        self, events: list[dict], variant: str, attempts: list[str]
    ) -> list:
        if variant not in ("G0", "G1") or not attempts:
            raise ValueError("choose G0 or G1 and nonempty development attempts")
        finished = self._finished(events)
        inputs = []
        for attempt_id in attempts:
            cell = self._cell(self._attempt(events, attempt_id)["cell"])
            if cell["stage"] not in ("explore", "provisional"):
                raise ValueError(
                    "maker inputs must precede final validation and holdout"
                )
            refs = finished[attempt_id]["maker_inputs"]
            if not {"sensors", "actions"} <= refs.keys():
                raise ValueError("development sensor/action evidence is missing")
            if cell["stage"] == "provisional" and "feedback" not in refs:
                raise ValueError("provisional Max call feedback is missing")
            _verify_refs(refs)
            allowed = {"sensors", "actions"}
            if variant == "G1" and cell["model"] == "qwen3.8-max":
                allowed.add("feedback")
            inputs.append(
                {
                    "attempt_id": attempt_id,
                    "files": {k: v for k, v in refs.items() if k in allowed},
                }
            )
        return inputs

    def maker_inputs(self, variant: str, attempts: list[str]) -> list:
        """Export only sanitized development inputs; never evaluator outcomes."""
        return self._transaction(
            lambda events: (self._maker_inputs(events, variant, attempts), None)
        )

    def reserve_offline(
        self,
        purpose: str,
        variant: str | None,
        attempts: list[str],
        *,
        maker_budget: dict | None = None,
        max_tokens: int = 0,
        revision: dict | None = None,
    ) -> str:
        """Charge one request before dispatch; retries also consume the cap of 80.

        Connectivity checks have no episode inputs or maker branch and use
        ``purpose="connectivity", variant=None, attempts=[]``. They remain
        available after freezing and share the same request budget.
        """

        def reserve(events):
            if revision is not None and purpose != "maker":
                raise ValueError("Revision binding is only valid for maker requests")
            if purpose != "connectivity" and any(e["kind"] == "frozen" for e in events):
                raise ValueError("offline development is closed after freezing")
            if sum(e["kind"] == "offline" for e in events) >= 80:
                raise ValueError("offline request budget exhausted")
            if purpose == "connectivity":
                if attempts != [] or variant is not None or maker_budget is not None:
                    raise ValueError(
                        "connectivity checks require no inputs, variant or maker budget"
                    )
                inputs = []
            else:
                inputs = self._maker_inputs(events, variant, attempts)
            if purpose == "maker":
                if (
                    not maker_budget
                    or any(
                        type(maker_budget.get(k)) is not int or maker_budget[k] <= 0
                        for k in ("max_calls", "max_tokens")
                    )
                    or type(max_tokens) is not int
                    or max_tokens <= 0
                ):
                    raise ValueError(
                        "maker requests need a shared budget and output token limit"
                    )
                prior = [
                    e
                    for e in events
                    if e["kind"] == "offline" and e["purpose"] == "maker"
                ]
                if any(e["maker_budget"] != maker_budget for e in prior):
                    raise ValueError("G0/G1 must share the same maker budget")
                branch = [e for e in prior if e["variant"] == variant]
                if (
                    len(branch) >= maker_budget["max_calls"]
                    or sum(e["max_tokens"] for e in branch) + max_tokens
                    > maker_budget["max_tokens"]
                ):
                    raise ValueError("maker branch budget exhausted")
                if revision is not None:
                    from robots.univtac.pilot import maker, maker_revision

                    if (
                        len(branch) != 1
                        or maker_budget != maker.BUDGET
                        or max_tokens != maker.PER_CALL_TOKENS
                    ):
                        raise ValueError(
                            "Paired refinement uses the second original maker call"
                        )
                    other_revisions = [
                        e.get("revision") for e in prior if e["variant"] != variant
                    ][1:]
                    if any(
                        not item or item["contract"] != revision["contract"]
                        for item in other_revisions
                    ):
                        raise ValueError(
                            "Both refinements must use the same paired contract"
                        )
                    maker_revision.validate_binding(
                        self, events, variant, inputs, revision
                    )
                elif any(e.get("revision") for e in prior):
                    raise ValueError("Both maker branches must use paired refinement")
            request_id = uuid.uuid4().hex
            return request_id, {
                "kind": "offline",
                "id": request_id,
                "purpose": purpose,
                "variant": variant,
                "inputs_hash": digest(inputs),
                "maker_budget": maker_budget,
                "max_tokens": max_tokens,
                **({"revision": revision} if revision is not None else {}),
            }

        return self._transaction(reserve)

    def finish_offline(self, request_id: str, result: dict) -> None:
        """Save returned usage, errors and replay evidence without refunding calls."""

        def finish(events):
            if not any(
                e["kind"] == "offline" and e["id"] == request_id for e in events
            ):
                raise ValueError("unknown offline request")
            if any(
                e["kind"] == "offline_result" and e["id"] == request_id for e in events
            ):
                raise ValueError("offline request is already finished")
            return None, {"kind": "offline_result", "id": request_id, "result": result}

        self._transaction(finish)

    def freeze(self, bundle: dict) -> str:
        """Seal conditions after six development attempts, before final validation.

        The bundle owns full tool source/declarations, guidance, parameters,
        controller, model settings and memory snapshots. A new bundle requires
        a new batch rather than replacing the current experiment.
        """
        required = {
            "conditions",
            "controller",
            "models",
            "memory",
            "code_revision",
            "base_tool",
            "maker_budget",
            "maker_input_attempts",
            "validation_evidence",
        }
        if not required <= bundle.keys() or not bundle["validation_evidence"]:
            raise ValueError(
                "complete frozen configuration and validation evidence required"
            )
        if set(bundle["conditions"]) != set("CDEF"):
            raise ValueError("freeze exactly C/D/E/F")
        for condition in bundle["conditions"].values():
            if not {"tools", "guidance", "parameters"} <= condition.keys():
                raise ValueError("each condition needs tools/guidance/parameters")
            for tool in condition["tools"]:
                if not {"name", "description", "parameters", "source"} <= tool.keys():
                    raise ValueError(
                        "freeze source, description and parameters for every tool"
                    )
                if not all(
                    isinstance(tool[key], str) and tool[key]
                    for key in ("name", "description", "source")
                ):
                    raise ValueError(
                        "tool names, descriptions and sources must be nonempty strings"
                    )
            if len({tool["name"] for tool in condition["tools"]}) != len(
                condition["tools"]
            ):
                raise ValueError("each tool name must have exactly one frozen version")
        base = bundle["conditions"]["C"]["tools"]
        if bundle["conditions"]["F"]["tools"] != base:
            raise ValueError("documentation control must use the same tools as C")
        for name in "DE":
            tools = bundle["conditions"][name]["tools"]
            if tools == base or any(tool not in tools for tool in base):
                raise ValueError("generated conditions must retain C and add a tool")
            if any(
                not tool["name"].startswith("sensor_")
                for tool in tools
                if tool not in base
            ):
                raise ValueError("generated conditions may only add perception tools")
        if any(
            bundle["maker_budget"].get(key, 0) <= 0
            for key in ("max_calls", "max_tokens")
        ):
            raise ValueError("one positive maker budget must apply to both G0 and G1")
        version = digest(bundle)

        def freeze(events):
            if any(e["kind"] == "frozen" for e in events):
                raise ValueError("batch is already frozen")
            finished = self._finished(events)
            if self.manifest["schema_version"] >= 2:
                if any(
                    e["kind"] == "reserved" and e["id"] not in finished for e in events
                ):
                    raise ValueError("finish the active attempt before freezing")
                for cell in self.manifest["cells"]:
                    if cell["stage"] != "infrastructure":
                        continue
                    if self.manifest["schema_version"] >= 3 and cell["id"] in (
                        "infra-01",
                        "infra-02",
                    ):
                        continue
                    if (
                        self.manifest["schema_version"] == 4
                        and cell["id"] == "infra-03"
                    ):
                        continue
                    attempt = next(
                        (
                            e
                            for e in events
                            if e["kind"] == "reserved" and e["cell"] == cell["id"]
                        ),
                        None,
                    )
                    if (
                        attempt is None
                        or finished.get(attempt["id"], {})
                        .get("outcome", {})
                        .get("checkpoint_validation_passed")
                        is not True
                    ):
                        raise ValueError(
                            "both infrastructure checkpoints must pass before freezing"
                        )
                if self.manifest["schema_version"] == 3:
                    from .checkpoint_protocol import verify_qualification

                    verify_qualification(self.manifest, events)
                elif self.manifest["schema_version"] == 4:
                    from .checkpoint_calibration import verify_qualification

                    verify_qualification(self.root, self.manifest, events)
            expected_inputs = []
            for cell in self.manifest["cells"][:6]:
                attempt = next(
                    (
                        e
                        for e in events
                        if e["kind"] == "reserved" and e["cell"] == cell["id"]
                    ),
                    None,
                )
                if attempt is None or attempt["id"] not in finished:
                    raise ValueError("first six development attempts must be recorded")
                if cell["stage"] != "smoke":
                    expected_inputs.append(attempt["id"])
            if bundle["maker_input_attempts"] != expected_inputs:
                raise ValueError(
                    "both makers must share all four development inputs in order"
                )
            maker_calls = [
                e for e in events if e["kind"] == "offline" and e["purpose"] == "maker"
            ]
            if any(e["maker_budget"] != bundle["maker_budget"] for e in maker_calls):
                raise ValueError("freeze must retain the recorded shared maker budget")
            from robots.univtac.pilot.maker_revision import (
                validate_binding,
                verified_maker_result,
            )

            revision_contracts = []
            for variant in ("G0", "G1"):
                inputs = self._maker_inputs(
                    events, variant, bundle["maker_input_attempts"]
                )
                calls = [e for e in maker_calls if e["variant"] == variant]
                if not calls or calls[-1]["inputs_hash"] != digest(inputs):
                    raise ValueError(
                        "both maker branches need the shared development inputs"
                    )
                if not any(
                    e["kind"] == "offline_result" and e["id"] == calls[-1]["id"]
                    for e in events
                ):
                    raise ValueError(
                        "maker request results must be recorded before freezing"
                    )
                candidate = verified_maker_result(self, events, calls[-1])
                condition = bundle["conditions"]["D" if variant == "G0" else "E"]
                generated = [tool for tool in condition["tools"] if tool not in base]
                if len(generated) != 1 or any(
                    generated[0].get(key) != value for key, value in candidate.items()
                ):
                    raise ValueError(
                        "Frozen generated tool differs from its maker candidate"
                    )
                binding = calls[-1].get("revision")
                revision_contracts.append(binding["contract"] if binding else None)
                if binding is not None:
                    validate_binding(self, events, variant, inputs, binding)
                    result = next(
                        e["result"]
                        for e in events
                        if e["kind"] == "offline_result" and e["id"] == calls[-1]["id"]
                    )
                    if result.get("revision") != binding:
                        raise ValueError(
                            "Maker result revision differs from its reservation"
                        )
            if revision_contracts[0] != revision_contracts[1]:
                raise ValueError(
                    "Both final makers must use the same paired refinement"
                )
            write_json_atomic(self.root / f"freeze-{version}.json", bundle)
            return version, {"kind": "frozen", "id": version}

        return self._transaction(freeze)

    def load_freeze(self, freeze_id: str) -> dict:
        """Load and verify the immutable configuration used for an attempt."""
        if len(freeze_id) != 64 or any(c not in "0123456789abcdef" for c in freeze_id):
            raise ValueError("invalid freeze id")
        bundle = json.loads((self.root / f"freeze-{freeze_id}.json").read_text())
        if digest(bundle) != freeze_id:
            raise ValueError("frozen configuration hash mismatch")
        return bundle

    def summary(self) -> dict:
        """Return counted attempts, outcomes and paired scene evidence."""

        def summarize(events):
            finished = self._finished(events)
            rows = []
            for event in events:
                if event["kind"] != "reserved":
                    continue
                outcome = finished.get(event["id"], {}).get("outcome", {})
                scene = next(
                    (
                        e
                        for e in events
                        if e["kind"] == "scene" and e["id"] == event["id"]
                    ),
                    {},
                )
                rows.append(
                    {
                        **outcome,
                        **self._cell(event["cell"]),
                        "attempt_id": event["id"],
                        "freeze_id": event["freeze_id"],
                        "scene_fingerprint": scene.get("fingerprint"),
                        "scene_matched": scene.get("matched"),
                    }
                )
                validation = next(
                    (
                        e
                        for e in events
                        if e["kind"] == "interface_validation"
                        and e["id"] == event["id"]
                    ),
                    None,
                )
                if validation is not None:
                    rows[-1].update(
                        interface_validation_passed=validation["passed"],
                        interface_validation_evidence=validation["evidence"],
                    )
            return {
                "schema_version": self.manifest["schema_version"],
                "episodes_reserved": len(rows),
                "episode_limit": self.manifest["max_episodes"],
                "development_limit": sum(
                    c["stage"] != "holdout" for c in self.manifest["cells"]
                ),
                "holdout_limits": dict(
                    Counter(
                        c["model"]
                        for c in self.manifest["cells"]
                        if c["stage"] == "holdout"
                    )
                ),
                "frozen": any(e["kind"] == "frozen" for e in events),
                "offline_requests": sum(e["kind"] == "offline" for e in events),
                "offline_limit": 80,
                "finished": len(finished),
                "termination_counts": dict(
                    Counter(r.get("termination_reason", "running") for r in rows)
                ),
                "rows": rows,
            }, None

        return self._transaction(summarize)
