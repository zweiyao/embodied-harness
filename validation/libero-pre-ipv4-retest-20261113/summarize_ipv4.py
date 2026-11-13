# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Build an IPv4-only table, replacing pre-switch cells without deleting them."""

import datetime
import json
import statistics
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
PARENT = BASE / "experiments/libero-object-t-qwenflash-original-50-ipv4-resume-20261113"
RETEST = BASE / "experiments/libero-object-t-qwenflash-pre-ipv4-retest-5-20261113"
OUT = BASE / "validation/libero-pre-ipv4-retest-20261113"

base = json.loads((PARENT / "results.json").read_text())
fresh = json.loads((RETEST / "results.json").read_text())
selected = [r for r in base if r["network_segment"] == "ipv4-direct"]
replaced = [r for r in base if r["network_segment"] == "direct-auto-before-resume"]


def keys(rows):
    return {(r["task"], r["seed"]) for r in rows}


assert len(fresh) == len(keys(fresh)) == 5
assert keys(fresh) == keys(replaced)
assert keys(fresh).isdisjoint(keys(selected))
rows = sorted(selected + fresh, key=lambda r: (r["task"], r["seed"]))
assert len(rows) == len(keys(rows))
assert all(r["network_segment"] == "ipv4-direct" for r in rows)
assert all(r["status"] in ["completed", "budget_exhausted"] for r in rows)


def total_tokens(row):
    return row["stats"]["total_input_tokens"] + row["stats"]["total_output_tokens"]


def score(data):
    successes = [r for r in data if r["success"]]
    return {
        "completed": len(data),
        "successes": len(successes),
        "success_rate_percent": 100 * len(successes) / len(data) if data else None,
        "mean_model_interactions": statistics.mean(r["model_requests"] for r in data)
        if data
        else None,
        "mean_episode_elapsed_s": statistics.mean(r["elapsed_s"] for r in data)
        if data
        else None,
        "mean_success_elapsed_s": statistics.mean(r["elapsed_s"] for r in successes)
        if successes
        else None,
        "mean_total_tokens": statistics.mean(total_tokens(r) for r in data)
        if data
        else None,
        "sum_total_tokens": sum(total_tokens(r) for r in data),
    }


summary = {
    "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "planned_unique_cells": 50,
    "network_segment": "ipv4-direct",
    "original_harness": True,
    "retested": [
        {
            k: r[k]
            for k in [
                "task",
                "seed",
                "success",
                "status",
                "model_requests",
                "elapsed_s",
                "url",
            ]
        }
        | {"total_tokens": total_tokens(r)}
        for r in fresh
    ],
    "retest_summary": score(fresh),
    "overall": score(rows),
    "tasks": [
        {"task": task, "planned": 5, **score([r for r in rows if r["task"] == task])}
        for task in range(10)
    ],
    "unfinished_cells": [
        {"task": t, "seed": s}
        for t in range(10)
        for s in range(5)
        if (t, s) not in keys(rows)
    ],
    "sources": {
        "ipv4_base_batch": str(PARENT),
        "five_cell_retest": str(RETEST),
        "excluded_pre_switch_cells": [list(k) for k in sorted(keys(replaced))],
    },
    "definitions": {
        "mean_scope": "Settled valid attempts including task failures; unresolved and infrastructure incidents excluded.",
        "interactions": "Model requests, not robot actions or tool calls.",
        "total_tokens": "Input + output usage; cached input is already part of input and is not added again.",
        "replacement": "The five repeats replace the same pre-switch cells in this derived table; old raw records remain intact.",
        "elapsed": "Mean episode elapsed includes valid failed attempts; successful completion time is stored separately.",
    },
}
assert sum(t["completed"] for t in summary["tasks"]) == len(rows)
assert (
    sum(t["sum_total_tokens"] for t in summary["tasks"])
    == summary["overall"]["sum_total_tokens"]
)
(OUT / "ipv4-only-results.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
)
(OUT / "ipv4-only-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
