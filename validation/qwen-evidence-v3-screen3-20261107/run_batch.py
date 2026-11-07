# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Run only the approved three cells on two isolated workbenches."""

import hashlib
import json
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from metrics import analyze, summarize

ROOT = Path(__file__).resolve().parent
PLAN = json.loads((ROOT / "plan.json").read_text())
INVARIANTS = json.loads((ROOT / "invariants.json").read_text())
LOCK = threading.Lock()
NEW_MEMORY = [
    "next-action-evidence.md",
    "object-relative-transfer.md",
    "grasp-feature-evidence.md",
]
GENERATED = ["sensor_patch_batch", "sensor_container_geometry"]


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def api(port, path, data=None, timeout=30):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}" + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def unchanged():
    assert all(
        hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
        for p, h in INVARIANTS["source_hashes"].items()
    ), "Protected files changed"


def classify(outcome):
    timeout = PLAN["config"]["planner_timeout_s"]
    if (
        outcome.get("status") == "timeout"
        and outcome.get("error") == f"planner timed out after {timeout:g}s"
        and (outcome.get("elapsed_s") or 0) >= timeout
    ):
        return "budget_timeout", False
    if (
        outcome.get("error")
        or outcome.get("status") not in ["completed", "budget_exhausted"]
        or type(outcome.get("environment_success")) is not bool
    ):
        return "unexpected", None
    return "task_result", outcome["environment_success"]


def aggregate():
    with LOCK:
        rows, states = [], {}
        for name in PLAN["lanes"]:
            path = ROOT / name
            if (path / "results.json").exists():
                rows += json.loads((path / "results.json").read_text())
            if (path / "status.json").exists():
                states[name] = json.loads((path / "status.json").read_text())
        phases = [s["phase"] for s in states.values()]
        phase = (
            "completed"
            if len(phases) == len(PLAN["lanes"])
            and all(s == "completed" for s in phases)
            else "stopped"
            if len(phases) == len(PLAN["lanes"])
            and all(s in ["completed", "stopped"] for s in phases)
            else "running"
        )
        save(ROOT / "results.json", rows)
        save(
            ROOT / "summary.json",
            {
                **summarize(rows),
                "planned": PLAN["total"],
                "success_rate_percent": 100
                * sum(r["evaluation_success"] for r in rows)
                / len(rows)
                if rows
                else None,
            },
        )
        save(
            ROOT / "status.json",
            {
                "phase": phase,
                "completed": len(rows),
                "planned": PLAN["total"],
                "lanes": states,
            },
        )


def validate_run(run):
    path = Path(run["path"]).resolve()
    assert path.is_relative_to(ROOT)
    expected = json.loads((Path(PLAN["materials"]) / "manifest.json").read_text())
    assert (
        json.loads((path / "language-materials/manifest.json").read_text()) == expected
    )
    assert all(
        hashlib.sha256((path / "language-materials" / p).read_bytes()).hexdigest() == h
        for p, h in expected["files"].items()
    )
    declarations = json.loads((path / "tool-declarations.json").read_text())
    assert sorted(t["name"] for t in declarations) == sorted(PLAN["tool_names"])
    metrics = analyze(path)
    assert metrics["memory_audit_passed"], "Successful read outside frozen run"
    reads = []
    for line in (path / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["kind"] != "tool_response":
            continue
        payload = event["payload"]
        result = payload.get("result")
        if (
            payload.get("name") == "read_text_file"
            and isinstance(result, dict)
            and "content" in result
        ):
            if Path(result.get("path", "")).name in NEW_MEMORY:
                reads.append(Path(result["path"]).name)
        if payload.get("name") in GENERATED and isinstance(result, dict):
            error = str(result.get("error", ""))
            assert not any(
                x in error.lower()
                for x in [
                    "docker",
                    "container exited",
                    "sandbox failed",
                    "permission denied",
                ]
            ), "Generated tool infrastructure error"
    metrics["new_experience_reads"] = reads
    metrics["generated_tool_calls"] = {
        n: metrics["tool_calls"].get(n, 0) for n in GENERATED
    }
    return metrics


def run_lane(name):
    lane = ROOT / name
    settings = PLAN["lanes"][name]
    port, trials = settings["port"], settings["trials"]
    config = PLAN["config"]
    rows = (
        json.loads((lane / "results.json").read_text())
        if (lane / "results.json").exists()
        else []
    )
    assert [(r["task"], r["seed"]) for r in rows] == [
        (t["task"], t["seed"]) for t in trials[: len(rows)]
    ]
    initial = api(port, "/api/session/state")
    try:
        for trial in trials[len(rows) :]:
            unchanged()
            assert api(port, "/api/session/config") == config
            state = api(port, "/api/session/state")
            assert state["server_id"] == initial["server_id"]
            existing = api(port, "/api/runs")["runs"]
            incidents = (
                json.loads((lane / "incidents.json").read_text())
                if (lane / "incidents.json").exists()
                else []
            )
            excluded = {r["path"] for r in rows + incidents}
            pending = [r for r in existing if r["path"] not in excluded]
            assert len(pending) <= 1, "Unexplained extra run"
            started = time.monotonic()
            if pending:
                run = pending[0]
                task = run["config"]["task"]
                assert (task["suite"], task["task"], task["seed"]) == (
                    PLAN["suite"],
                    trial["task"],
                    trial["seed"],
                )
                known = {r["id"] for r in existing if r["id"] != run["id"]}
            else:
                assert state["session_state"] == "ready"
                known = {r["id"] for r in existing}
                save(
                    lane / "status.json",
                    {"phase": "starting", **trial, "completed": len(rows)},
                )
                aggregate()
                api(
                    port,
                    "/api/session/messages",
                    {
                        "text": f"/rpent-task {PLAN['suite']} {trial['task']} {trial['seed']}"
                    },
                )
            while time.monotonic() - started < 900:
                time.sleep(5)
                state = api(port, "/api/session/state")
                assert state["server_id"] == initial["server_id"], "Workbench restarted"
                fresh = [
                    r for r in api(port, "/api/runs")["runs"] if r["id"] not in known
                ]
                assert len(fresh) <= 1, "Concurrent run in same environment"
                run = fresh[0] if fresh else None
                save(
                    lane / "status.json",
                    {
                        "phase": "running",
                        **trial,
                        "completed": len(rows),
                        "run_id": run["id"] if run else None,
                        "elapsed_s": round(time.monotonic() - started, 1),
                    },
                )
                aggregate()
                if run:
                    task = run["config"]["task"]
                    assert (task["suite"], task["task"], task["seed"]) == (
                        PLAN["suite"],
                        trial["task"],
                        trial["seed"],
                    )
                    if run["outcome"] and state["session_state"] == "ready":
                        break
                elif state.get("error"):
                    raise RuntimeError(state["error"])
            else:
                raise TimeoutError(
                    "Episode did not finalize; leave running for inspection"
                )
            outcome = run["outcome"]
            category, success = classify(outcome)
            row = {
                "lane": name,
                **trial,
                "run_id": run["id"],
                "path": run["path"],
                "classification": category,
                "evaluation_success": success,
                "official_success": outcome.get("environment_success"),
                "status": outcome.get("status"),
                "error": outcome.get("error"),
                "elapsed_s": outcome.get("elapsed_s"),
                "stats": outcome.get("stats", {}),
                "actions": outcome.get("actions"),
                "material_version": PLAN["material_version"],
                "planner_timeout_s": 300,
            }
            if category != "unexpected":
                try:
                    row["metrics"] = validate_run(run)
                except Exception as exc:
                    row.update(
                        classification="unexpected",
                        evaluation_success=None,
                        audit_error=str(exc),
                    )
            if row["classification"] == "unexpected":
                save(lane / "incidents.json", incidents + [row])
                raise RuntimeError(
                    "Unexpected incident excluded; diagnose before retry"
                )
            rows.append(row)
            save(lane / "results.json", rows)
            unchanged()
            aggregate()
            print(json.dumps(row, ensure_ascii=False), flush=True)
        save(lane / "status.json", {"phase": "completed", "completed": len(rows)})
    except Exception as exc:
        save(
            lane / "status.json",
            {"phase": "stopped", "completed": len(rows), "error": str(exc)},
        )
    finally:
        aggregate()


if __name__ == "__main__":
    assert json.loads((ROOT / "preflight.json").read_text())["passed"]
    unchanged()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_lane, name) for name in PLAN["lanes"]]
        for future in futures:
            future.result()
    aggregate()
    if json.loads((ROOT / "status.json").read_text())["phase"] == "completed":
        subprocess.run(["python3", str(ROOT / "cleanup.py")], check=True)
