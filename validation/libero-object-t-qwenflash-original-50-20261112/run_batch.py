# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Run the fixed two-lane Object-T evaluation without elapsed-time budgets."""

import hashlib
import json
import os
import shutil
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAN = json.loads((ROOT / "plan.json").read_text())
INVARIANTS = json.loads((ROOT / "invariants.json").read_text())
LOCK = threading.RLock()
STOP = threading.Event()
ACTIONS = {
    "move_pose",
    "move_to",
    "pi0_doubled",
    "pi0_pick",
    "release",
    "rotate_pitch",
    "rotate_wrist",
    "set_gripper",
}


def save(p, value):
    temporary = p.with_suffix(p.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(p)


def api(port, path, data=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}" + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=None) as response:
        return json.load(response)


def unchanged():
    assert all(
        hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
        for p, digest in INVARIANTS["source_hashes"].items()
    ), "Protected source/material/config changed"


def aggregate():
    with LOCK:
        rows = []
        states = {}
        for lane in PLAN["lanes"]:
            p = ROOT / lane
            if (p / "results.json").exists():
                rows += json.loads((p / "results.json").read_text())
            if (p / "status.json").exists():
                states[lane] = json.loads((p / "status.json").read_text())

        def score(xs):
            return {
                "completed": len(xs),
                "successes": sum(r["success"] for r in xs),
                "success_rate_percent": 100 * sum(r["success"] for r in xs) / len(xs)
                if xs
                else None,
            }

        save(ROOT / "results.json", rows)
        save(
            ROOT / "summary.json",
            {
                **score(rows),
                "planned": 50,
                "by_task": {
                    str(t): score([r for r in rows if r["task"] == t])
                    for t in range(10)
                },
                "final": len(rows) == 50,
                "configuration": PLAN["configuration"],
            },
        )
        save(
            ROOT / "status.json",
            {
                "phase": "completed"
                if len(rows) == 50
                else "stopped"
                if STOP.is_set()
                else "running",
                "completed": len(rows),
                "planned": 50,
                "lanes": states,
            },
        )


def metrics(path):
    events = [json.loads(s) for s in (path / "events.jsonl").read_text().splitlines()]
    calls = [e["payload"] for e in events if e["kind"] == "tool_request"]
    first = next((i for i, c in enumerate(calls) if c.get("name") in ACTIONS), None)
    requests = [e["payload"] for e in events if e["kind"] == "model_request"]
    responses = [e for e in events if e["kind"] == "model_response"]
    assert 0 < len(requests) <= 50
    for request in requests:
        settings = request.get("model_settings", {})
        assert settings.get("timeout", "missing") is None, (
            "Model HTTP timeout still enabled"
        )
        assert settings.get("extra_body", {}).get("enable_thinking") is False
    declarations = json.loads((path / "tool-declarations.json").read_text())
    assert sorted(t["name"] for t in declarations) == sorted(
        t.removeprefix("native:") for t in PLAN["configuration"]["tools"]
    )
    frozen = json.loads((path / "language-materials/manifest.json").read_text())
    original = json.loads((Path(PLAN["materials"]) / "manifest.json").read_text())
    assert frozen == original
    assert all(
        hashlib.sha256((path / "language-materials" / n).read_bytes()).hexdigest() == h
        for n, h in frozen["files"].items()
    )
    return {
        "model_requests": len(requests),
        "completed_model_responses": len(responses),
        "tool_calls": len(calls),
        "before_first_action_tool_calls": first,
        "action_tool_calls": sum(c.get("name") in ACTIONS for c in calls),
    }


def publish(path, public_session):
    target = Path(public_session) / "tasks" / path.name
    assert not target.exists(), "Never overwrite public evidence"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(path, target, copy_function=os.link, symlinks=True)
    identity = str(target.relative_to("/home/zwy/work/embodied_harness/research-runs"))
    return {
        "path": str(target),
        "id": hashlib.sha256(identity.encode()).hexdigest()[:20],
    }


def run_lane(name, lane):
    directory = ROOT / name
    port = lane["port"]
    rows = []
    run = None
    trial = None
    try:
        initial = api(port, "/api/session/state")
        assert initial["session_state"] == "ready"
        expected = PLAN["configuration"]
        assert api(port, "/api/session/config") == expected
        for trial in lane["trials"]:
            if STOP.is_set():
                break
            unchanged()
            state = api(port, "/api/session/state")
            assert (
                state["session_state"] == "ready"
                and state["server_id"] == initial["server_id"]
            )
            assert api(port, "/api/session/config") == expected
            known = {r["id"] for r in api(port, "/api/runs")["runs"]}
            started = time.monotonic()
            run = None
            api(
                port,
                "/api/session/messages",
                {
                    "text": f"/rpent-task {PLAN['suite']} {trial['task']} {trial['seed']}"
                },
            )
            while True:
                time.sleep(2)
                state = api(port, "/api/session/state")
                assert state["server_id"] == initial["server_id"]
                fresh = [
                    r for r in api(port, "/api/runs")["runs"] if r["id"] not in known
                ]
                assert len(fresh) <= 1
                run = fresh[0] if fresh else None
                save(
                    directory / "status.json",
                    {
                        "phase": "running",
                        **trial,
                        "completed": len(rows),
                        "run_id": run["id"] if run else None,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "usage": state.get("usage"),
                    },
                )
                aggregate()
                if run and run["outcome"] and state["session_state"] == "ready":
                    break
                if run is None and state.get("error"):
                    raise RuntimeError(state["error"])
            assert run["config"]["task"]["suite"] == PLAN["suite"]
            assert all(run["config"]["task"][k] == trial[k] for k in ["task", "seed"])
            outcome = run["outcome"]
            path = Path(run["path"])
            assert path.is_relative_to(directory / "runs")
            assert not outcome.get("error") and outcome["status"] in [
                "completed",
                "budget_exhausted",
            ], outcome
            assert type(outcome.get("environment_success")) is bool
            measurement = metrics(path)
            public = publish(path, lane["public_session"])
            row = {
                **trial,
                "success": outcome["environment_success"],
                "status": outcome["status"],
                "run_id": run["id"],
                "path": str(path),
                "public_id": public["id"],
                "public_path": public["path"],
                "url": "http://10.162.250.228:8092/runs?id=" + public["id"],
                "elapsed_s": outcome.get("elapsed_s"),
                **measurement,
                "stats": outcome.get("stats", {}),
                "instruction": run.get("instruction"),
            }
            rows.append(row)
            save(directory / "results.json", rows)
            aggregate()
            print(json.dumps({"lane": name, **row}, ensure_ascii=False), flush=True)
        save(
            directory / "status.json",
            {
                "phase": "completed" if len(rows) == 25 else "stopped",
                "completed": len(rows),
            },
        )
        aggregate()
    except Exception as exc:
        STOP.set()
        save(
            directory / "incident.json",
            {
                "trial": trial,
                "run_id": run["id"] if run else None,
                "path": run["path"] if run else None,
                "error": str(exc),
                "counted_as_result": False,
            },
        )
        save(
            directory / "status.json",
            {"phase": "incident", "completed": len(rows), "error": str(exc)},
        )
        aggregate()
        raise


def main():
    assert not (ROOT / "started.json").exists(), "Do not duplicate a live batch"
    unchanged()
    save(
        ROOT / "started.json",
        {
            "at_unix": time.time(),
            "planned": 50,
            "time_limit_s": None,
            "model_requests_per_episode": 50,
        },
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(run_lane, name, lane) for name, lane in PLAN["lanes"].items()
        ]
        for future in futures:
            future.result()
    aggregate()
    if len(json.loads((ROOT / "results.json").read_text())) == 50:
        import subprocess

        for lane in PLAN["lanes"].values():
            subprocess.run(["systemctl", "--user", "stop", lane["unit"]], check=True)


if __name__ == "__main__":
    main()
