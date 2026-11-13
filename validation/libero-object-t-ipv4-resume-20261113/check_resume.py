# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Check continuation accounting with simulated API outcomes; no model calls."""

import contextlib
import copy
import importlib.util
import io
import json
import shutil
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
ROOT = BASE / "experiments/libero-object-t-qwenflash-original-50-ipv4-resume-20261113"
OUT = BASE / "validation/libero-object-t-ipv4-resume-20261113"
spec = importlib.util.spec_from_file_location("batch", ROOT / "run_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
plan = copy.deepcopy(batch.PLAN)
dry = OUT / "simulated-accounting"
assert not dry.exists()
dry.mkdir()
for name in plan["lanes"]:
    (dry / name).mkdir()
    shutil.copyfile(ROOT / name / "results.json", dry / name / "results.json")
batch.ROOT = dry
batch.unchanged = lambda: None
batch.time.sleep = lambda _: None
batch.metrics = lambda _: {"model_requests": 1, "completed_model_responses": 1}
batch.publish = lambda path, _: {"path": str(path), "id": path.name}
history = {lane["port"]: [] for lane in plan["lanes"].values()}
owners = {lane["port"]: name for name, lane in plan["lanes"].items()}
dispatched = []
incident = False


def api(port, path, data=None):
    if path == "/api/session/config":
        return plan["configuration"]
    if path == "/api/session/state":
        return {"session_state": "ready", "server_id": str(port), "usage": {}}
    if path == "/api/runs":
        return {"runs": history[port]}
    assert path == "/api/session/messages"
    _, suite, task, seed = data["text"].split()
    task, seed = int(task), int(seed)
    dispatched.append((task, seed))
    path = dry / owners[port] / "runs" / f"simulated-{task}-{seed}"
    history[port].append(
        {
            "id": path.name,
            "path": str(path),
            "config": {"task": {"suite": suite, "task": task, "seed": seed}},
            "outcome": {
                "error": "simulated infrastructure incident" if incident else None,
                "status": "completed",
                "environment_success": seed % 2 == 0,
            },
        }
    )


batch.api = api
with contextlib.redirect_stdout(io.StringIO()):
    for name, lane in plan["lanes"].items():
        batch.run_lane(name, lane)
rows = json.loads((dry / "results.json").read_text())
assert len(dispatched) == len(set(dispatched)) == 45
assert len(rows) == len({(r["task"], r["seed"]) for r in rows}) == 50
assert sum(r["network_segment"] == "direct-auto-before-resume" for r in rows) == 5
assert sum(r["network_segment"] == "ipv4-direct" for r in rows) == 45
assert any(not r["success"] for r in rows)
assert json.loads((dry / "summary.json").read_text())["final"] is True

# A new infrastructure incident must retain the five old results and add none.
for name in plan["lanes"]:
    shutil.copyfile(ROOT / name / "results.json", dry / name / "results.json")
incident = True
batch.STOP.clear()
history = {lane["port"]: [] for lane in plan["lanes"].values()}
try:
    batch.run_lane("b", plan["lanes"]["b"])
except AssertionError:
    pass
else:
    raise AssertionError("Incident was incorrectly accepted")
assert len(json.loads((dry / "results.json").read_text())) == 5
assert json.loads((dry / "b/incident.json").read_text())["counted_as_result"] is False
assert batch.STOP.is_set()
result = {
    "passed": True,
    "simulated_new_valid_results": 45,
    "combined_unique_trials": 50,
    "retained": 5,
    "valid_task_failures_counted": True,
    "infrastructure_incident_excluded": True,
    "real_model_calls": 0,
    "real_robot_actions": 0,
}
(OUT / "accounting-check.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
