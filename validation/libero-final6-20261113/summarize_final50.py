# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Combine the 44 retained IPv4 cells and six completions exactly once."""

import datetime
import json
import statistics
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
ROOT = BASE / "experiments/libero-object-t-qwenflash-ipv4-final6-20261113"
PARENT = BASE / "experiments/libero-object-t-qwenflash-original-50-ipv4-resume-20261113"
RETEST = BASE / "experiments/libero-object-t-qwenflash-pre-ipv4-retest-5-20261113"
OUT = BASE / "validation/libero-final6-20261113"


def score(rows):
    successes = [r for r in rows if r["success"]]
    tokens = [
        r["stats"]["total_input_tokens"] + r["stats"]["total_output_tokens"]
        for r in rows
    ]
    return {
        "completed": len(rows),
        "successes": len(successes),
        "success_rate_percent": 100 * len(successes) / len(rows),
        "mean_model_interactions": statistics.mean(r["model_requests"] for r in rows),
        "mean_episode_elapsed_s": statistics.mean(r["elapsed_s"] for r in rows),
        "mean_success_elapsed_s": statistics.mean(r["elapsed_s"] for r in successes)
        if successes
        else None,
        "mean_total_tokens": statistics.mean(tokens),
        "sum_total_tokens": sum(tokens),
    }


def main():
    parent = json.loads((PARENT / "results.json").read_text())
    retained = [r for r in parent if r["network_segment"] == "ipv4-direct"]
    retests = json.loads((RETEST / "results.json").read_text())
    new = json.loads((ROOT / "results.json").read_text())
    assert len(retained) == 40 and len(retests) == 4 and len(new) == 6
    rows = sorted(retained + retests + new, key=lambda r: (r["task"], r["seed"]))
    assert len(rows) == 50
    assert {(r["task"], r["seed"]) for r in rows} == {
        (t, s) for t in range(10) for s in range(5)
    }
    assert all(r["network_segment"] == "ipv4-direct" for r in rows)
    assert all(
        r["status"] in ["completed", "budget_exhausted", "model_stopped_without_finish"]
        for r in rows
    )
    summary = {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "is_final": True,
        "planned_unique_cells": 50,
        "overall": score(rows),
        "tasks": [
            {"task": t, "planned": 5, **score([r for r in rows if r["task"] == t])}
            for t in range(10)
        ],
        "sources": {
            "retained_ipv4": str(PARENT),
            "four_retests": str(RETEST),
            "six_completions": str(ROOT),
        },
        "excluded": "All five pre-IPv4 cells; infrastructure incidents; two operator-interrupted attempts, retained separately. No valid task failure was retried.",
        "early_stop_policy": json.loads((ROOT / "plan.json").read_text())[
            "early_stop_policy"
        ],
        "definitions": {
            "interactions": "model requests",
            "elapsed": "all settled valid runs including failures",
            "tokens": "input plus output; cached input is already included",
        },
    }
    assert sum(t["completed"] for t in summary["tasks"]) == 50
    assert (
        sum(t["sum_total_tokens"] for t in summary["tasks"])
        == summary["overall"]["sum_total_tokens"]
    )
    for name, data in [
        ("ipv4-only-results.json", rows),
        ("ipv4-only-summary.json", summary),
    ]:
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
