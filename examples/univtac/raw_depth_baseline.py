# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Run ten full simulator episodes through an idle UniVTAC dashboard.

Run on the dashboard host so archived events can be read without exporting
observations. Configure/check the model first. No model replay or retries.
"""

import argparse
import csv
import hashlib
import json
import time
import urllib.request
from collections import Counter
from pathlib import Path

from rpent.dashboard.workbench import RunJournal, write_json

TOOLS = {"observe", "read_image", "read_depth", "tactile_stats", "move_eef", "finish"}
USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


def submit_trial(api, journal: RunJournal, task: int, seed: int) -> None:
    """Keep the cell identity even when the dashboard never returns an outcome."""
    cell = {"task": task, "seed": seed}
    journal.append("submission_started", cell)
    api("/api/session/messages", {"text": f"/rpent-task univtac {task} {seed}"})
    journal.append("submission_accepted", cell)


def verify_trial_identity(run, state, task: int, seed: int) -> None:
    """The run catalog also indexes other sessions and restored history roots."""
    actual = (run.get("config") or {}).get("task")
    cell = (actual.get("task"), actual.get("seed")) if isinstance(actual, dict) else ()
    run_id = run.get("id")
    if not run_id or state.get("run_id") != run_id or cell != (task, seed):
        raise RuntimeError(
            f"Unexpected finalized run {run_id} for cell {cell}; "
            f"expected session run {state.get('run_id')} for cell {(task, seed)}"
        )


def summarize_outcomes(rows: list[dict]) -> dict:
    """Separate clean native verdicts from interrupted or unadjudicated attempts.

    The original successes/trials fields count all true flags and all attempts.
    A timeout can occur during reset, model wait or the planner deadline. Keep
    its recorded flag and termination available for protocol-specific scoring.
    """
    successes = failures = 0
    other_attempts = {}
    for row in rows:
        verdict = row.get("official_success")
        termination = row.get("termination") or "unreported"
        if (
            termination in {"completed", "budget_exhausted"}
            and not row.get("error")
            and type(verdict) is bool
        ):
            if verdict:
                successes += 1
            else:
                failures += 1
        else:
            signal = "unreported"
            if verdict is True:
                signal = "official_true"
            elif verdict is False:
                signal = "official_false"
            other_attempts.setdefault(termination, Counter())[signal] += 1
    return {
        "successes": sum(row.get("official_success") is True for row in rows),
        "trials": len(rows),
        "evaluated": {
            "successes": successes,
            "failures": failures,
            "trials": successes + failures,
        },
        "other_attempts": other_attempts,
    }


def summarize(run):
    """Use official outcomes and provider-reported cumulative usage only."""
    outcome = run["outcome"]
    stats = outcome.get("stats") or {}
    updates, zero_usage = {}, {}
    calls, tool_seconds = {}, 0.0
    try:
        lines = (Path(run["path"]) / "events.jsonl").read_text().splitlines()
    except FileNotFoundError:
        lines = None
    for line in lines or ():
        event = json.loads(line)
        payload = event["payload"]
        if (
            event["kind"] == "sdk_event"
            and payload.get("method") == "thread/tokenUsage/updated"
        ):
            total = (payload["payload"].get("token_usage") or {}).get("total")
            if isinstance(total, dict):
                reported = {
                    k: total[k] for k in USAGE_FIELDS if total.get(k) is not None
                }
                # The SDK can replay an earlier cumulative notification. Updating
                # its existing entry preserves the order of distinct responses.
                # Zero defaults identify duplicate count vectors. Keep the
                # original fields for reporting omitted measurements.
                key = tuple(reported.get(k, 0) for k in USAGE_FIELDS)
                if any(key):
                    updates.setdefault(key, {}).update(reported)
                else:
                    zero_usage.update(reported)
        if event["kind"] == "tool_response":
            name = payload["name"]
            calls[name] = calls.get(name, 0) + 1
            tool_seconds += payload.get("elapsed_s", 0.0)
    usage = next(reversed(updates.values()), zero_usage)
    return {
        "run_id": run["id"],
        "path": run["path"],
        "official_success": outcome.get("environment_success"),
        "termination": outcome.get("termination_reason") or outcome.get("status"),
        "error": outcome.get("error"),
        "elapsed_s": outcome.get("elapsed_s"),
        "planner_elapsed_s": stats.get("elapsed_s"),
        "tool_execution_s": round(tool_seconds, 3) if lines is not None else None,
        "tool_calls": calls if lines is not None else None,
        "decisions": stats.get("turns_used"),
        **{name: usage.get(name) for name in USAGE_FIELDS},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8093")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, data=None):
        request = urllib.request.Request(
            args.url + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
        with opener.open(request, timeout=20) as response:
            return json.load(response)

    config = api("/api/session/config")
    assert set(config["tools"]) == {"native:" + name for name in TOOLS}
    assert config["model"] == "gpt-6-astra" and config["reasoning_effort"] == "high"
    initial = api("/api/session/state")
    assert initial["session_state"] == "ready"
    catalog = api("/api/tools")["tools"]
    selected = [t for t in catalog if t["id"] in config["tools"]]
    sources = [
        Path("robots/univtac") / name for name in ("prompt_bundle.py", "toolkit.py")
    ]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    trials = [{"task": task, "seed": seed} for task in (1, 2) for seed in range(5)]
    planned = Counter(trial["task"] for trial in trials)
    write_json(
        args.output / "protocol.json",
        {
            "config": config,
            "tools": selected,
            "source_hashes": hashes,
            "trials": trials,
            "denominator_per_task": 5,
            "retries": 0,
            "timing": "planner time includes tools and SDK overhead; it is not pure network latency",
            "tokens": "provider cumulative usage; null means unreported; cached is part of input and reasoning part of output",
        },
    )
    results = []
    journal = RunJournal(args.output)
    try:
        for trial in trials:
            assert api("/api/session/config") == config, (
                "Configuration changed; batch stopped"
            )
            state = api("/api/session/state")
            assert state["server_id"] == initial["server_id"], "Dashboard restarted"
            assert state["session_state"] == "ready", "Another run is active"
            assert all(
                hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                for p, h in hashes.items()
            )
            known = {r["id"] for r in api("/api/runs")["runs"]}
            started = time.monotonic()
            write_json(
                args.output / "status.json",
                {"phase": "starting", **trial, "completed": len(results)},
            )
            submit_trial(api, journal, trial["task"], trial["seed"])
            run = None
            while time.monotonic() - started < 4500:
                time.sleep(10)
                state = api("/api/session/state")
                assert state["server_id"] == initial["server_id"], "Dashboard restarted"
                fresh = [r for r in api("/api/runs")["runs"] if r["id"] not in known]
                assert len(fresh) <= 1, "Unexpected concurrent run"
                run = fresh[0] if fresh else None
                write_json(
                    args.output / "status.json",
                    {
                        "phase": "running",
                        **trial,
                        "completed": len(results),
                        "run_id": run["id"] if run else None,
                        "elapsed_s": round(time.monotonic() - started, 1),
                    },
                )
                if run and run["outcome"] and state["session_state"] == "ready":
                    verify_trial_identity(run, state, trial["task"], trial["seed"])
                    break
                if not run and state.get("error"):
                    raise RuntimeError(state["error"])
            else:
                raise TimeoutError(
                    "Run not finalized; batch stopped without starting another episode"
                )
            result = {
                **trial,
                **summarize(run),
                "batch_wall_s": round(time.monotonic() - started, 1),
            }
            results.append(result)
            write_json(args.output / "results.json", results)
            with (args.output / "results.csv").open("w") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(results[0]))
                writer.writeheader()
                writer.writerows(results)
            print(json.dumps(result), flush=True)
            write_json(
                args.output / "summary.json",
                {
                    str(task): {
                        "planned_trials": expected,
                        **summarize_outcomes([r for r in results if r["task"] == task]),
                    }
                    for task, expected in planned.items()
                },
            )
        write_json(
            args.output / "status.json",
            {"phase": "completed", "completed": len(results)},
        )
    except Exception as exc:
        write_json(
            args.output / "status.json",
            {"phase": "stopped", "completed": len(results), "error": str(exc)},
        )
        raise


if __name__ == "__main__":
    main()
