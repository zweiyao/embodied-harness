# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Finalize the existing two episodes; never dispatch or repeat an experiment."""

import fcntl
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import run_batch as runner
from model_argument_failure import argument_failure_evidence

ROOT = Path(__file__).resolve().parent
lock = (ROOT / ".batch.lock").open("a")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
assert json.loads((ROOT / "classification-checks.json").read_text())["passed"]
runner.unchanged()
observed_at = datetime.now(timezone.utc).isoformat()
preflight = json.loads((ROOT / "preflight.json").read_text())
live = {
    "observed_at": observed_at,
    "audit_type": "retrospective_workbench_processes_after_episode_end",
    "environment_children_directly_observed": False,
    "environment_child_command_lines": None,
    "environment_child_proxy_snapshot": None,
    "eef_wrapper_absence": "inferred from frozen selection/setup/preflight; no contemporaneous child command snapshot",
    "lanes": [],
}
proxy_keys = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]
for name, lane in runner.PLAN["lanes"].items():
    state = runner.api(lane["port"], "/api/session/state")
    expected = next(r["server_id"] for r in preflight["lanes"] if r["lane"] == name)
    assert state["server_id"] == expected
    assert state["session_state"] == "ready" and state["pending_task"] is None
    assert not state["operator"]["active"]
    runs = runner.api(lane["port"], "/api/runs")["runs"]
    assert len(runs) == 1 and runs[0]["outcome"] is not None
    pid = int(
        subprocess.check_output(
            ["systemctl", "--user", "show", lane["unit"], "-p", "MainPID", "--value"],
            text=True,
        )
    )
    proc = Path("/proc") / str(pid)
    env = dict(
        x.split(b"=", 1)
        for x in (proc / "environ").read_bytes().split(b"\0")
        if b"=" in x
    )
    command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode()
    paths = {
        key: env.get(key.encode(), b"").decode()
        for key in ["RPENT_REPO_ROOT", "PYTHONPATH"]
    }
    row = {
        "lane": name,
        "pid": pid,
        "server_id": state["server_id"],
        "server_matches_preflight": state["server_id"] == expected,
        "session_state": state["session_state"],
        "episode_ended_at": runs[0]["outcome"]["ended_at"],
        "command": command,
        "source_environment": paths,
        "source_roots_match": paths["RPENT_REPO_ROOT"] == runner.PLAN["runtime_source"]
        and runner.PLAN["runtime_source"] in paths["PYTHONPATH"].split(":"),
        "proxy_variables_present": [k for k in proxy_keys if k.encode() in env],
    }
    live["lanes"].append(row)
live["workbench_source_roots_match"] = all(
    r["source_roots_match"] for r in live["lanes"]
)
live["workbench_proxy_variables_absent"] = all(
    not r["proxy_variables_present"] for r in live["lanes"]
)
live["workbench_servers_match_preflight"] = all(
    r["server_matches_preflight"] for r in live["lanes"]
)
runner.save(ROOT / "live-audit.json", live)

incident_path = ROOT / "a/incidents.json"
incident_bytes = incident_path.read_bytes()
incident = json.loads(incident_bytes)[0]
path = Path(incident["path"])
outcome_bytes = (path / "outcome.json").read_bytes()
outcome = json.loads(outcome_bytes)
proof = argument_failure_evidence(path, outcome)
assert proof and outcome["actions"] == 0 and outcome["last_completed_step"] == 0
assert runner.classify(outcome, 600, run_path=path) == ("model_argument_error", False)
row = {
    **incident,
    "classification": "model_argument_error",
    "evaluation_success": False,
    "classification_evidence": "classification-corrections.json",
    "metrics": runner.validate_run({"path": str(path)}, runner.PLAN["lanes"]["a"]),
}
correction = {
    "observed_at": observed_at,
    "path": str(path),
    "from_classification": "unexpected",
    "to_classification": "model_argument_error",
    "evaluation_success": False,
    "original_incident_sha256": hashlib.sha256(incident_bytes).hexdigest(),
    "original_outcome_sha256": hashlib.sha256(outcome_bytes).hexdigest(),
    "events_sha256": hashlib.sha256((path / "events.jsonl").read_bytes()).hexdigest(),
    "evidence": proof,
    "rerun": False,
    "sdk_retry_limit_changed": False,
    "reason": "Both model replies violate the same actual/published schema; correction prompt was supplied; rejected calls never entered tool implementation. Valid model failure under the original protocol.",
}
assert not (ROOT / "classification-corrections.json").exists()
runner.save(ROOT / "classification-corrections.json", [correction])
runner.save(ROOT / "a/results.json", [row])
runner.save(
    ROOT / "a/status.json",
    {"phase": "completed", "completed": 1, "classification_corrected": True},
)
runner.aggregate()
assert incident_path.read_bytes() == incident_bytes
assert (path / "outcome.json").read_bytes() == outcome_bytes
runner.unchanged()
print(json.dumps({"classified_valid_failure": True, "completed": 2, "rerun": False}))
