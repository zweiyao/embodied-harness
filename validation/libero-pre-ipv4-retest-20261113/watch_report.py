# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Observe the five-cell batch and generate its replacement table when ready."""

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
ROOT = BASE / "experiments/libero-object-t-qwenflash-pre-ipv4-retest-5-20261113"
OUT = BASE / "validation/libero-pre-ipv4-retest-20261113"
PORT = json.loads((ROOT / "plan.json").read_text())["lanes"]["a"]["port"]


def record(phase, **fields):
    path = OUT / "report-status.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"at_unix": time.time(), "phase": phase, **fields}, indent=2) + "\n"
    )
    temp.replace(path)


while True:
    rows = json.loads((ROOT / "results.json").read_text())
    status = json.loads((ROOT / "status.json").read_text())
    if len(rows) == 5:
        with (OUT / "summary-generation.log").open("w") as stream:
            subprocess.run(
                [sys.executable, str(OUT / "summarize_ipv4.py")],
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=True,
            )
        record("completed", retested=5, summary=str(OUT / "ipv4-only-summary.json"))
        break
    if status["phase"] == "stopped":
        record("batch_stopped", completed=len(rows), status=status)
        break
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/api/session/state", timeout=10
        ) as response:
            state = json.load(response)
        interaction = state.get("interaction", {})
        if (
            state.get("session_state") == "running"
            and interaction.get("planner_activity") == "idle"
        ):
            record(
                "awaiting_evaluation_decision",
                completed=len(rows),
                active=status["lanes"]["a"],
                counted_as_result=False,
                classified_as_infrastructure=False,
                message="Model turn ended; workbench awaits user input. Observer sends no follow-up and changes no task outcome.",
            )
            break
        record("waiting", completed=len(rows), active=status["lanes"]["a"])
    except (OSError, ValueError) as exc:
        record("observation_error", completed=len(rows), error=str(exc))
    time.sleep(10)
