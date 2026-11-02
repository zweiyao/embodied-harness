# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Freeze an improving chat-authored tool and evaluate ten held-out episodes."""

import argparse
import json
from pathlib import Path

from examples.univtac.develop_tools import NATIVE, Experiment, score, valid_tool_calls
from robots.libero.research.library import Library, digest
from rpent.dashboard.workbench import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8093")
    args = parser.parse_args()
    evaluation = json.loads((args.development / "evaluation.json").read_text())
    measured, baseline = evaluation["score"], evaluation["baseline"]
    if not (
        measured["successes"] == measured["trials"] == 3
        and measured["mean_total_tokens"] is not None
        and measured["mean_total_tokens"] < baseline["mean_total_tokens"]
        and evaluation["calls"]["valid_calls"] > 0
    ):
        raise ValueError(
            "Development has not demonstrated the required measured benefit"
        )
    protocol = json.loads((args.development / "protocol.json").read_text())
    tool = json.loads((args.development / "candidate.json").read_text())
    version = digest([tool])
    if version != protocol["tool_version"] or Library(args.library).load(version) != [
        tool
    ]:
        raise ValueError("Published tool differs from the development snapshot")
    experiment = Experiment(args.url, args.output)
    if experiment.hashes != protocol["sources"] or any(
        experiment.base_config[k] != protocol["base_config"][k]
        for k in (
            "model",
            "reasoning_effort",
            "max_turns",
            "max_tokens",
            "planner_timeout_s",
        )
    ):
        raise ValueError("Development runtime or budget changed")
    args.output.mkdir(parents=True, exist_ok=False)
    trials = [(task, seed) for task in (1, 2) for seed in range(5)]
    write_json(
        args.output / "freeze.json",
        {
            "development": str(args.development),
            "tool_version": version,
            "tool": tool,
            "sources": experiment.hashes,
            "trials": trials,
            "configuration": experiment.base_config,
            "rule": "No tool, prompt or threshold changes during testing; stop on infrastructure error; no retries",
            "author": "current Codex conversation",
            "remote_maker_requests": 0,
        },
    )
    try:
        rows = experiment.group(
            "frozen-test", trials, NATIVE + ["generated:" + version]
        )
        write_json(
            args.output / "summary.json",
            {
                "overall": score(rows),
                "calls": valid_tool_calls(rows),
                "by_task": {
                    str(task): score([r for r in rows if r["task"] == task])
                    for task in (1, 2)
                },
                "scope": "Astra only; small-sample frozen-task reuse, not Qwen or unseen-model transfer evidence",
            },
        )
        experiment.status(state="completed", completed=len(rows))
    finally:
        if experiment.api("/api/session/state")["session_state"] == "ready":
            experiment.api("/api/session/config", {"tools": NATIVE})


if __name__ == "__main__":
    main()
