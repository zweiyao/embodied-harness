# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare the authorized IPv4 continuation without changing archived runs."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
OLD = BASE / "experiments/libero-object-t-qwenflash-original-50-20261112"
ROOT = BASE / "experiments/libero-object-t-qwenflash-original-50-ipv4-resume-20261113"
ARCHIVE = BASE / "validation/libero-object-t-qwenflash-original-50-20261112"
OUT = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def api(port, path):
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=10
    ) as response:
        return json.load(response)


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert not ROOT.exists(), "Never overwrite a continuation"
old_plan = json.loads((OLD / "plan.json").read_text())
old_invariants = json.loads((OLD / "invariants.json").read_text())
assert all(digest(Path(p)) == h for p, h in old_invariants["source_hashes"].items())
prior = json.loads((OLD / "results.json").read_text())
assert len(prior) == 5
completed = {(r["task"], r["seed"]) for r in prior}
assert len(completed) == 5
assert completed == {(0, 0), (0, 2), (0, 4), (1, 1), (1, 3)}
prior_by_lane = {}
for name, lane in old_plan["lanes"].items():
    state = api(lane["port"], "/api/session/state")
    assert state["session_state"] == "ready" and state["pending_task"] is None
    assert api(lane["port"], "/api/session/config") == old_plan["configuration"]
    indexed = {r["id"]: r for r in api(lane["port"], "/api/runs")["runs"]}
    rows = (
        json.loads((OLD / name / "results.json").read_text())
        if (OLD / name / "results.json").exists()
        else []
    )
    for row in rows:
        run = indexed[row["run_id"]]
        assert run["outcome"]["status"] in ["completed", "budget_exhausted"]
        assert not run["outcome"].get("error")
        assert type(run["outcome"]["environment_success"]) is bool
        assert run["outcome"]["environment_success"] == row["success"]
        assert run["path"] == row["path"]
        row.update(network_segment="direct-auto-before-resume", origin_batch=str(OLD))
    prior_by_lane[name] = rows
assert sum(len(rows) for rows in prior_by_lane.values()) == 5

prepare = (ARCHIVE / "prepare_batch.py").read_text()
prepare = replace_once(prepare, str(OLD.relative_to(BASE)), str(ROOT.relative_to(BASE)))
prepare = replace_once(
    prepare, "rpent-object-t-qwenflash-'", "rpent-object-t-qwenflash-ipv4-'"
)
prepare = replace_once(prepare, "-20261112.service", "-20261113.service")
prepare = replace_once(
    prepare,
    "research-runs/libero-object-t-qwenflash-original-50-20261112-",
    "research-runs/libero-object-t-qwenflash-original-50-ipv4-resume-20261113-",
)
snapshot = OUT / "prepare_batch.snapshot.py"
snapshot.write_text(prepare)
subprocess.run([sys.executable, str(snapshot)], check=True)

plan = json.loads((ROOT / "plan.json").read_text())
for key in [
    "configuration",
    "suite",
    "materials",
    "material_version",
    "source",
    "time_policy",
    "incident_policy",
]:
    assert plan[key] == old_plan[key], key
launched_revision = json.loads((ARCHIVE / "launch-evidence.json").read_text())[
    "runtime_revision"
]
assert (
    plan["base_revision"]
    == launched_revision
    == "59181787c873e537aff5c3f81e4d90f19b38cfa3"
)
new_invariants = json.loads((ROOT / "invariants.json").read_text())
assert new_invariants["source_hashes"] == old_invariants["source_hashes"]
plan.update(
    parent_batch=str(OLD),
    retained_valid=5,
    remaining=45,
    approved_user_request="用ipv4继续qwen做实验",
    network_segment="ipv4-direct",
    network="Inherit remote-network.sh direct-ipv4 selection; no networking overrides in experiment code.",
)
remaining = []
for name, lane in plan["lanes"].items():
    lane["trials"] = [
        t for t in lane["trials"] if (t["task"], t["seed"]) not in completed
    ]
    remaining.extend((t["task"], t["seed"]) for t in lane["trials"])
    save(ROOT / name / "results.json", prior_by_lane[name])
    save(
        ROOT / name / "status.json",
        {"phase": "prepared", "completed": len(prior_by_lane[name])},
    )
assert len(remaining) == len(set(remaining)) == 45
assert set(remaining).isdisjoint(completed)
assert set(remaining) | completed == {(t, s) for t in range(10) for s in range(5)}
assert (0, 1) in remaining
save(ROOT / "plan.json", plan)

driver = (OLD / "run_batch.py").read_text()
driver = replace_once(
    driver,
    "    rows = []\n    run = None",
    '    rows = json.loads((directory / "results.json").read_text())\n    run = None',
)
driver = replace_once(
    driver,
    "            row = {\n                **trial,",
    '            row = {\n                "network_segment": PLAN["network_segment"],\n                "origin_batch": str(ROOT),\n                **trial,',
)
driver = replace_once(
    driver,
    '            "planned": 50,\n            "time_limit_s": None,',
    '            "planned": 50,\n            "retained_valid": 5,\n            "remaining": 45,\n            "time_limit_s": None,',
)
(ROOT / "run_batch.py").write_text(driver)
shutil.copyfile(OLD / "trace_workbench.py", ROOT / "trace_workbench.py")

launch = (ARCHIVE / "launch_preflight.py").read_text()
launch = replace_once(launch, str(OLD), str(ROOT))
launch = replace_once(
    launch,
    "assert not [k for k in env if k.lower() in ['http_proxy','https_proxy','all_proxy']]",
    "assert all(env.get(k)=='http://127.0.0.1:47040' for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'])\n        assert not any(env.get(k) for k in ['ALL_PROXY','all_proxy'])",
)
launch = replace_once(launch, "'direct_network':True", "'ipv4_network_selected':True")
(ROOT / "launch_preflight.py").write_text(launch)

spec = importlib.util.spec_from_file_location("continuation", ROOT / "run_batch.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.aggregate()
assert json.loads((ROOT / "summary.json").read_text())["completed"] == 5
prepared = json.loads((ROOT / "status.json").read_text())
prepared["phase"] = "prepared"
save(ROOT / "status.json", prepared)
save(
    ROOT / "continuation-provenance.json",
    {
        "at_unix": time.time(),
        "parent_batch": str(OLD),
        "parent_results_sha256": digest(OLD / "results.json"),
        "parent_driver_sha256": digest(OLD / "run_batch.py"),
        "parent_preparation_revision": old_plan["base_revision"],
        "actual_launch_and_continuation_revision": launched_revision,
        "retained_trials": [list(t) for t in sorted(completed)],
        "remaining_trials": [list(t) for t in remaining],
        "preserved_incident": str(OLD / "b/incident.json"),
        "incident_counted_as_result": False,
        "model_calls_made": 0,
        "retained_network_segment": "direct-auto-before-resume",
        "remaining_network_segment": "ipv4-direct",
        "timing_policy": "Report network segments separately; no causal speed or success-rate inference across segments.",
        "harness_configuration_unchanged": True,
    },
)
print(
    json.dumps(
        {
            "root": str(ROOT),
            "retained": 5,
            "remaining": 45,
            "lanes": {
                n: {"port": x["port"], "unit": x["unit"], "remaining": len(x["trials"])}
                for n, x in plan["lanes"].items()
            },
        }
    ),
    flush=True,
)
