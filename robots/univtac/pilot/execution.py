# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Connect RPent lifecycle hooks to the fixed pilot ledger, without a planner."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from robots.univtac.pilot import TERMINATIONS, Pilot
from rpent.dashboard.workbench import termination_reason
from rpent.evaluation.result import write_json_atomic

BUDGET = {
    "max_turns": 60,
    "planner_timeout_s": 3600,
    "model_request_timeout_s": 300,
}
PROFILE_FIELDS = {"planner", "model", "reasoning_effort", "base_url", "max_tokens"}


def tools_match_for_execution(selected: list[dict], frozen: list[dict]) -> bool:
    """Compare ordered executable definitions, ignoring catalog display metadata."""
    fields = (
        "name",
        "origin",
        "version",
        "source",
        "description",
        "parameters",
        "dependencies",
    )

    def execution_data(tools):
        return json.dumps(
            [
                {
                    key: tool.get(key, [] if key == "dependencies" else None)
                    for key in fields
                }
                for tool in tools
            ],
            sort_keys=True,
            allow_nan=False,
        )

    return execution_data(selected) == execution_data(frozen)


class PilotExecution:
    """One already-reserved episode and its immutable effective configuration."""

    def __init__(self, pilot: Pilot, output_dir: Path, record: dict):
        self.pilot, self.output_dir, self.record = pilot, output_dir, record

    @property
    def attempt_id(self):
        return self.record["attempt_id"]

    @property
    def selected(self):
        return copy.deepcopy(self.record["selected"])

    @property
    def guidance(self):
        return self.record["guidance"]

    @property
    def parameters(self):
        return copy.deepcopy(self.record["parameters"])

    @property
    def sandbox_image(self):
        """Resolved image ID; never resolve the mutable tag again for this run."""
        return (
            self.record.get("actual_evidence", {})
            .get("controller", {})
            .get("sandbox_image")
        )

    def _save(self):
        write_json_atomic(self.output_dir / "pilot-attempt.json", self.record)

    def after_reset(self, evaluator: dict) -> str:
        """Require initial private scene evidence before any model or action."""
        try:
            fingerprint = self.pilot.record_scene(self.attempt_id, evaluator["scene"])
        except (KeyError, ValueError) as exc:
            reason = (
                "scene_mismatch" if "scene mismatch" in str(exc) else "setup_failure"
            )
            self.after_finish({"termination_reason": reason, "error": str(exc)})
            raise
        self.record["scene_fingerprint"] = fingerprint
        self._save()
        return fingerprint

    def after_finish(self, outcome: dict) -> dict:
        """Record termination separately from the official evaluator success."""
        if "outcome" in self.record:
            return copy.deepcopy(self.record["outcome"])
        result = copy.deepcopy(outcome)
        explicit = result.get("termination_reason", result.get("status"))
        aliases = {"error": "failed", "configuration_error": "setup_failure"}
        if explicit is None:
            explicit = termination_reason(
                result.get("error"),
                result.get("aborted", False),
                result.get("finish"),
                result.get("environment_success", False),
            )
        reason = aliases.get(explicit, explicit)
        if reason not in TERMINATIONS:
            raise ValueError(f"Unknown pilot termination: {reason}")
        official = result.get("official_success", result.get("environment_success"))
        if official is not None and type(official) is not bool:
            raise ValueError("Official success must be a boolean or null")
        result.update(termination_reason=reason, native_success=official)
        self.pilot.finish_episode(self.attempt_id, result)
        self.record["outcome"] = result
        self._save()
        return copy.deepcopy(result)


def restore_from_output(output_dir: str | Path) -> PilotExecution | None:
    """Reopen a reservation without charging; ordinary runs return ``None``."""
    output_dir = Path(output_dir).resolve()
    path = output_dir / "pilot-attempt.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record["output_dir"] != str(output_dir):
        raise ValueError("Pilot reservation belongs to another output directory")
    pilot = Pilot(record["pilot_root"])

    def recover(events):
        attempt = pilot._attempt(events, record["attempt_id"])
        if (attempt["session_id"], attempt["cell"], attempt["freeze_id"]) != (
            str(output_dir),
            record["cell"]["id"],
            record["freeze_id"],
        ):
            raise ValueError("Pilot metadata differs from its ledger reservation")
        return pilot._finished(events).get(record["attempt_id"]), None

    finished = pilot._transaction(recover)
    if finished:
        record["outcome"] = finished["outcome"]
    return PilotExecution(pilot, output_dir, record)


def before_start(
    pilot_root: str | Path,
    cell_id: str,
    output_dir: str | Path,
    model: str,
    task: str,
    seed: int,
    selected: list[dict] | None,
    budget: dict,
    freeze_id: str | None = None,
    *,
    model_profile_settings: dict | None = None,
    actual_evidence: dict | None = None,
) -> PilotExecution:
    """Validate the actual run configuration, then charge before simulator startup.

    The caller must apply ``selected`` and ``guidance`` from the returned object.
    Tool thresholds belong in frozen source/schemas; condition-level parameters
    are unsupported. Frozen model settings are compared to the actual planner
    configuration here; this function does not instantiate another planner.
    ``actual_evidence`` comes from provenance.collect(), and is mandatory for
    frozen conditions; the same measured code, controller and memory must run.
    """
    from robots.univtac.toolkit import native_catalog, validate_selection

    pilot = Pilot(pilot_root)
    cell = pilot._cell(cell_id)
    if (model, task, seed) != (cell["model"], cell["task"], cell["seed"]):
        raise ValueError("model/task/seed must match the reserved protocol cell")
    if (
        budget != BUDGET
        or type(budget["max_turns"]) is not int
        or any(
            type(budget[key]) not in (int, float)
            for key in ("planner_timeout_s", "model_request_timeout_s")
        )
    ):
        raise ValueError(
            "Pilot requires 60 responses, 3600 seconds, 300-second model-response waits"
        )
    profile = copy.deepcopy(model_profile_settings or {})
    if model != "script" and set(profile) != PROFILE_FIELDS:
        raise ValueError(
            "Provide the actual planner/model/reasoning/base_url/max_tokens profile"
        )
    evidence = copy.deepcopy(actual_evidence or {})
    if freeze_id is not None:
        bundle = pilot.load_freeze(freeze_id)
        if not evidence or any(
            evidence.get(key) != bundle[key]
            for key in ("controller", "code_revision", "memory")
        ):
            raise ValueError(
                "Actual controller/code/memory evidence differs from the frozen bundle"
            )
        if (
            bundle["models"]["budget"] != budget
            or bundle["models"]["profiles"].get(model) != profile
        ):
            raise ValueError(
                "Actual model profile or budget differs from the frozen bundle"
            )
        condition = copy.deepcopy(bundle["conditions"][cell["condition"]])
    elif cell["condition"] == "C":
        condition = {"tools": native_catalog(), "guidance": "", "parameters": {}}
    elif cell["condition"] == "provisional" and selected is not None:
        condition = {"tools": copy.deepcopy(selected), "guidance": "", "parameters": {}}
    else:
        raise ValueError(
            "This condition requires a frozen bundle or explicit provisional tools"
        )
    if selected is not None and not tools_match_for_execution(
        selected, condition["tools"]
    ):
        raise ValueError(
            "Selected tools differ from the fixed condition; no silent replacement"
        )
    if condition["parameters"] != {}:
        raise ValueError(
            "Condition parameters must be empty; freeze thresholds in tool source/schema"
        )
    validate_selection(condition["tools"])
    output_dir = Path(output_dir).resolve()
    if (output_dir / "pilot-attempt.json").exists():
        raise ValueError("Output already has a pilot reservation")
    output_dir.mkdir(parents=True, exist_ok=True)
    attempt = pilot.reserve_episode(cell_id, str(output_dir), freeze_id)
    record = {
        "pilot_root": str(pilot.root.resolve()),
        "output_dir": str(output_dir),
        "attempt_id": attempt,
        "cell": copy.deepcopy(cell),
        "freeze_id": freeze_id,
        "selected": condition["tools"],
        "guidance": condition["guidance"],
        "parameters": condition["parameters"],
        "model_profile_settings": profile,
        "actual_evidence": evidence,
        "budget": copy.deepcopy(budget),
    }
    execution = PilotExecution(pilot, output_dir, record)
    try:
        execution._save()
    except OSError as exc:
        pilot.finish_episode(
            attempt, {"termination_reason": "setup_failure", "error": str(exc)}
        )
        raise
    return execution
