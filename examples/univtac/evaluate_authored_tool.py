# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Evaluate a chat-authored candidate in task 0 without invoking a remote maker."""

import argparse
import json
from pathlib import Path

from examples.univtac.develop_tools import (
    NATIVE,
    Experiment,
    better,
    score,
    valid_tool_calls,
)
from robots.libero.research.library import Sandbox, digest, validate_tools
from rpent.dashboard.workbench import publish, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8093")
    args = parser.parse_args()
    tool = json.loads(args.candidate.read_text())
    validate_tools([tool])
    replay = json.loads(args.replay.read_text())
    if (
        replay["tool_version"] != digest([tool])
        or not replay["reports"]
        or any(r["result"].get("error") for r in replay["reports"])
    ):
        raise ValueError("Candidate needs a matching, nonempty sandbox replay")
    args.output.mkdir(parents=True, exist_ok=False)
    experiment = Experiment(args.url, args.output)
    previous = json.loads((args.baseline / "protocol.json").read_text())
    baseline = json.loads(
        (args.baseline / "development-baseline/results.json").read_text()
    )
    if (
        previous["sources"] != experiment.hashes
        or previous["sandbox_image"] != Sandbox("embodied-sensor:pilot").image
        or any(
            previous["base_config"][k] != experiment.base_config[k]
            for k in (
                "model",
                "reasoning_effort",
                "max_turns",
                "max_tokens",
                "planner_timeout_s",
            )
        )
        or len(baseline) != 3
        or {(r["task"], r["seed"]) for r in baseline} != {(0, s) for s in range(3)}
    ):
        raise ValueError("Baseline runtime, budget or development scenes differ")
    write_json(args.output / "candidate.json", tool)
    write_json(
        args.output / "protocol.json",
        {
            "author": "current Codex conversation",
            "remote_maker_requests": 0,
            "development_trials": [[0, s] for s in range(3)],
            "baseline": str(args.baseline),
            "sources": experiment.hashes,
            "base_config": experiment.base_config,
            "tool_version": digest([tool]),
            "heldout_trials": 0,
            "rule": "Review development feedback before another revision or frozen test",
        },
    )
    active = experiment.api("/api/tools")["tools"]
    if any(
        t["id"].startswith("generated:")
        and t.get("selectable", True)
        and not (args.library / (t["id"].removeprefix("generated:") + ".json")).exists()
        for t in active
    ):
        raise ValueError("Library differs from the active dashboard")
    previous_version = next(
        (
            t["id"].removeprefix("generated:")
            for t in active
            if t["id"].startswith("generated:") and t.get("name") == tool["name"]
        ),
        None,
    )
    version = publish(
        args.library,
        tool,
        {
            "validation": "replay_passed",
            "author": "current Codex conversation",
            "source_run": "task0 development; see " + str(args.replay),
            "reason": "Compute calibrated local geometry from selected depth patches; evaluate effect on repeated queries and alignment reasoning.",
            "input_contract": "Latest four UniVTAC sensor frames; native metric optical-Z depth, camera intrinsics and world ROS optical pose. Select an ROI at its recorded resolution. No evaluator state.",
            "example": replay["reports"][-1]["result"],
            **({"previous_version": previous_version} if previous_version else {}),
        },
    )
    try:
        rows = experiment.group(
            "development", [(0, s) for s in range(3)], NATIVE + ["generated:" + version]
        )
        measured, reference = score(rows), score(baseline)
        write_json(
            args.output / "evaluation.json",
            {
                "score": measured,
                "baseline": reference,
                "calls": valid_tool_calls(rows),
                "improved": better(measured, reference),
                "note": "Development only. Authoring effort in this chat has no provider usage record; not zero-cost. Held-out evaluation has not run.",
            },
        )
        experiment.status(
            state="completed", completed=3, improved=better(measured, reference)
        )
    finally:
        if experiment.api("/api/session/state")["session_state"] == "ready":
            experiment.api("/api/session/config", {"tools": NATIVE})


if __name__ == "__main__":
    main()
