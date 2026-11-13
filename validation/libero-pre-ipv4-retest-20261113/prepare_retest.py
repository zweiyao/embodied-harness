# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare exactly the five requested IPv4 replacements; preserve all old runs."""

import ast
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
ORIGINAL = BASE / "experiments/libero-object-t-qwenflash-original-50-20261112"
PARENT = BASE / "experiments/libero-object-t-qwenflash-original-50-ipv4-resume-20261113"
ROOT = BASE / "experiments/libero-object-t-qwenflash-pre-ipv4-retest-5-20261113"
ARCHIVE = BASE / "validation/libero-object-t-qwenflash-original-50-20261112"
OUT = Path(__file__).resolve().parent


def replace(text, old, new, count=1):
    assert text.count(old) == count, (old, text.count(old))
    return text.replace(old, new)


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


assert not ROOT.exists()
parent_plan = json.loads((PARENT / "plan.json").read_text())
parent_rows = json.loads((PARENT / "results.json").read_text())
old_rows = [
    r for r in parent_rows if r["network_segment"] == "direct-auto-before-resume"
]
trials = [{"task": r["task"], "seed": r["seed"]} for r in old_rows]
assert [(t["task"], t["seed"]) for t in trials] == [
    (0, 0),
    (0, 2),
    (0, 4),
    (1, 1),
    (1, 3),
]

prepare = (ARCHIVE / "prepare_batch.py").read_text()
prepare = replace(prepare, str(ORIGINAL.relative_to(BASE)), str(ROOT.relative_to(BASE)))
prepare = replace(
    prepare, "rpent-object-t-qwenflash-'", "rpent-qwenflash-ipv4-retest-'"
)
prepare = replace(prepare, "-20261112.service", "-20261113.service")
prepare = replace(
    prepare,
    "research-runs/libero-object-t-qwenflash-original-50-20261112-",
    "research-runs/libero-object-t-qwenflash-pre-ipv4-retest-5-20261113-",
)

driver = (ORIGINAL / "run_batch.py").read_text()
driver = replace(driver, '"planned": 50', '"planned": PLAN["total"]', 3)
driver = replace(driver, "len(rows) == 50", 'len(rows) == PLAN["total"]', 2)
driver = replace(driver, "len(rows) == 25", 'len(rows) == len(lane["trials"])')
driver = replace(
    driver,
    'len(json.loads((ROOT / "results.json").read_text())) == 50',
    'len(json.loads((ROOT / "results.json").read_text())) == PLAN["total"]',
)
driver = replace(
    driver,
    "            row = {\n                **trial,",
    '            row = {\n                "network_segment": PLAN["network_segment"],\n                "origin_batch": str(ROOT),\n                **trial,',
)

launch = (ARCHIVE / "launch_preflight.py").read_text()
launch = replace(launch, str(ORIGINAL), str(ROOT))
launch = replace(
    launch,
    "assert not [k for k in env if k.lower() in ['http_proxy','https_proxy','all_proxy']]",
    "assert all(env.get(k)=='http://127.0.0.1:47040' for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'])\n        assert not any(env.get(k) for k in ['ALL_PROXY','all_proxy'])",
)
launch = replace(launch, "'direct_network':True", "'ipv4_network_selected':True")
launch = replace(
    launch,
    "len({x['server_id'] for x in results})==2",
    "len({x['server_id'] for x in results})==len(PLAN['lanes'])",
)
header = driver.split('"""', 1)[0]
launch = header + launch
for code in [prepare, driver, launch]:
    ast.parse(code)

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
    "base_revision",
    "time_policy",
    "incident_policy",
]:
    assert plan[key] == parent_plan[key], key
lane = plan["lanes"]["a"]
lane["trials"] = trials
plan.update(
    total=5,
    tasks=[0, 1],
    lanes={"a": lane},
    network_segment="ipv4-direct",
    parent_batch=str(PARENT),
    approved_user_request="把那5次重新测一下吧ipv4之前的",
    retest_policy="Replace these five cells in a derived IPv4-only table; retain every old raw record. Never repeat a valid failure to obtain success.",
)
save(ROOT / "plan.json", plan)
save(ROOT / "a/results.json", [])
save(ROOT / "a/status.json", {"phase": "prepared", "completed": 0})
(ROOT / "run_batch.py").write_text(driver)
(ROOT / "launch_preflight.py").write_text(launch)
shutil.copyfile(PARENT / "trace_workbench.py", ROOT / "trace_workbench.py")

spec = importlib.util.spec_from_file_location("retest", ROOT / "run_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
batch.aggregate()
status = json.loads((ROOT / "status.json").read_text())
status["phase"] = "prepared"
save(ROOT / "status.json", status)
save(
    ROOT / "provenance.json",
    {
        "parent_batch": str(PARENT),
        "retested_cells": trials,
        "old_parent_results_sha256": hashlib.sha256(
            (PARENT / "results.json").read_bytes()
        ).hexdigest(),
        "original_five_records": [
            {k: r[k] for k in ["task", "seed", "path", "public_id"]} for r in old_rows
        ],
        "harness_configuration_unchanged": True,
        "network_profile": "direct-ipv4",
        "existing_waiting_task_8_seed_1_untouched": True,
        "new_environments": 1,
        "existing_idle_dashboard_preserved": True,
        "unsettled_policy": "Observe and report model-turn idle states; no automatic follow-up prompt, no classification as infrastructure, and no altered failure definition.",
    },
)
print(
    json.dumps(
        {
            "root": str(ROOT),
            "trials": trials,
            "unit": lane["unit"],
            "port": lane["port"],
        }
    ),
    flush=True,
)
