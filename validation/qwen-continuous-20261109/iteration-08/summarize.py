# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Summarize completed08 policy costs without changing evaluation decisions."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


assert read("status.json")["phase"] == "completed"
assert read("final-verification.json")["passed"] and read("cleanup.json")["passed"]
rows = read("results.json")
assert len(rows) == len({row["path"] for row in rows}) == 2
assert {row["task"] for row in rows} == {0, 4}
assert all(
    row["classification"] in {"task_result", "budget_timeout", "model_argument_error"}
    for row in rows
)
cells = []
for row in rows:
    stats, metrics = row["stats"], row["metrics"]
    cells.append(
        {
            "cell_id": row["path"],
            "task": row["task"],
            "condition": row["condition"],
            "official_success": row["official_success"],
            "classification": row["classification"],
            "model_requests": stats["turns_used"],
            "input_tokens_including_cached": stats["total_input_tokens"],
            "cached_input_tokens_subset": stats["total_cached_input_tokens"],
            "output_tokens": stats["total_output_tokens"],
            "elapsed_s": row["elapsed_s"],
            "completed_responses": metrics["completed_model_responses"],
            "completed_wait_s": metrics["completed_model_wait_sum_s"],
            "toolkit_action_entries": metrics["action_calls"],
            "before_action_calls": metrics["before_action_calls"],
            "first_action_s": metrics["first_action_seconds_since_first_event"],
            "finish_only": metrics["finish_only"],
        }
    )
cost = {"valid_attempts": len(rows)}
for key in (
    "model_requests",
    "input_tokens_including_cached",
    "cached_input_tokens_subset",
    "output_tokens",
):
    cost[key] = sum(cell[key] for cell in cells)
cost["summed_outcome_elapsed_s"] = round(sum(cell["elapsed_s"] for cell in cells), 3)
report = {
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    **cost,
    "cells": cells,
    "completed_responses": sum(cell["completed_responses"] for cell in cells),
    "completed_wait_s": sum(cell["completed_wait_s"] for cell in cells),
    "preflight_connectivity_requests_excluded": 2,
    "notes": [
        "Cached input is a subset, not additive; canceled usage is not estimated.",
        "Tool entry/accepted finish do not establish holding or official success.",
        "Historical parent and timing/lane confounds remain separate.",
    ],
}
entry = {
    "iteration": 8,
    "source": "iteration-08/results.json",
    "sha256": hashlib.sha256((ROOT / "results.json").read_bytes()).hexdigest(),
    "cost": cost,
    "cell_paths": [cell["cell_id"] for cell in cells],
}
delta = {
    "recorded_at": report["recorded_at"],
    "by_iteration_entry": entry,
    "separate_connectivity_requests_without_usage_delta": 2,
}
for name, data in (
    ("cost-summary.json", report),
    ("resource-ledger-delta.json", delta),
):
    (ROOT / name).write_text(json.dumps(data, indent=2) + "\n")
print(json.dumps(cost))
