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
from pathlib import Path

from rpent.dashboard.workbench import write_json

TOOLS = {"observe", "read_image", "read_depth", "tactile_stats", "move_eef", "finish"}


def summarize(run):
    """Use official outcomes and provider-reported cumulative usage only."""
    outcome = run["outcome"]
    usage, calls, tool_seconds = {}, {}, 0.0
    for line in (Path(run["path"]) / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        payload = event["payload"]
        if (
            event["kind"] == "sdk_event"
            and payload.get("method") == "thread/tokenUsage/updated"
        ):
            usage = payload["payload"]["token_usage"].get("total", {})
        if event["kind"] == "tool_response":
            name = payload["name"]
            calls[name] = calls.get(name, 0) + 1
            tool_seconds += payload.get("elapsed_s", 0.0)
    return {
        "run_id": run["id"],
        "path": run["path"],
        "official_success": outcome.get("environment_success"),
        "termination": outcome.get("status"),
        "error": outcome.get("error"),
        "elapsed_s": outcome.get("elapsed_s"),
        "planner_elapsed_s": outcome.get("stats", {}).get("elapsed_s"),
        "tool_execution_s": round(tool_seconds, 3),
        "tool_calls": calls,
        "decisions": outcome.get("stats", {}).get("turns_used"),
        **{
            name: usage.get(name)
            for name in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )
        },
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
            api(
                "/api/session/messages",
                {"text": f"/rpent-task univtac {trial['task']} {trial['seed']}"},
            )
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
                    "successes": sum(
                        r["official_success"] is True
                        for r in results
                        if r["task"] == task
                    ),
                    "trials": 5,
                }
                for task in (1, 2)
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
