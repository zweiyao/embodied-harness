# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare one frozen task-0 diagnostic; no model call or environment action."""

import hashlib
import json
import shutil
import socket
import urllib.request
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
OLD = BASE / "experiments/qwen-continuous-20261109/iteration-11"
ROOT = BASE / "experiments/qwen-task0-upload-20261111"
assert not ROOT.exists()
ROOT.mkdir()
(ROOT / "a").mkdir()


def save(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2) + "\n")


def api(path):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8092" + path, timeout=15))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


plan = json.loads((OLD / "plan.json").read_text())
source = Path(plan["runtime_source"])
handoff = json.loads((OLD / "source-handoff.json").read_text())
for rel, h in handoff["source_files_sha256"].items():
    assert sha(source / rel) == h, rel
state = api("/api/session/state")
assert state["session_state"] == "ready" and not state["operator"]["active"]
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
plan.update(
    total=1,
    lanes={
        "a": {
            **plan["lanes"]["a"],
            "port": port,
            "unit": "rpent-qwen-task0-upload-20261111.service",
        }
    },
    route="inherit externally selected remote network",
    approval="User requested script network separation and one Qwen task0 upload diagnostic",
    comparison="Single diagnostic using frozen iteration11 R18+W2+F+V+A+I, same PNG/settings; not a success-rate comparison",
)
plan.pop("selection_difference", None)
plan["benchmark"]["private_bddl"] = str(ROOT / "benchmark/bddl_files")
shutil.copytree(OLD / "benchmark", ROOT / "benchmark")
shutil.copytree(OLD / "a/libero-config", ROOT / "a/libero-config")
p = ROOT / "a/libero-config/config.yaml"
p.write_text(p.read_text().replace(str(OLD), str(ROOT)))
w = json.loads((OLD / "a/workbench.json").read_text())
w["runs_root"] = str(ROOT / "a/runs")
save(ROOT / "a/workbench.json", w)
(ROOT / "a/workbench.json").chmod(0o600)
shutil.copy2(
    OLD / "a/expected-selected-tools.json", ROOT / "a/expected-selected-tools.json"
)
for name in [
    "run_batch.py",
    "cleanup.py",
    "runtime_audit.py",
    "metrics.py",
    "finish_metrics.py",
    "workflow_metrics.py",
    "model_argument_failure.py",
]:
    text = (
        (OLD / name)
        .read_text()
        .replace(
            "urllib.request.build_opener(urllib.request.ProxyHandler({}))",
            "urllib.request.build_opener()",
        )
    )
    if name == "runtime_audit.py":
        text = text.replace(
            'if args[1:3] == ["-m", "rpent.cli.main"]',
            'if args[1:3] == ["-m", "rpent.cli.main"] or (len(args) > 1 and args[1] == str(self.root / "trace_workbench.py"))',
        )
    (ROOT / name).write_text(text)
for name in ["trace_workbench.py", "start.py", "test_trace.py"]:
    shutil.copy2(BASE / "debug/qwen-task0-upload-20261111" / name, ROOT / name)
start = (
    (OLD / "a/start.sh")
    .read_text()
    .replace(str(OLD), str(ROOT))
    .replace(
        "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy\n", ""
    )
    .replace(
        "--dashboard-port "
        + str(json.loads((OLD / "plan.json").read_text())["lanes"]["a"]["port"]),
        "--dashboard-port " + str(port),
    )
    .replace(
        "exec python -m rpent.cli.main",
        f"exec python {ROOT}/trace_workbench.py {ROOT}/http-trace.jsonl",
    )
)
(ROOT / "a/start.sh").write_text(start)
(ROOT / "start_batch.sh").write_text(
    f"#!/bin/bash\nset -euo pipefail\ncd {BASE}\nsource /home/zwy/work/harnessvla/local-setup/activate.sh\nexport RPENT_REPO_ROOT={source}\nexport PYTHONPATH={source} HF_HUB_OFFLINE=1\npython {ROOT}/start.py\npython {ROOT}/run_batch.py\n"
)
save(ROOT / "plan.json", plan)
# Freeze source, selected material and operational files at this diagnostic's start.
protected = {str(source / rel): h for rel, h in handoff["source_files_sha256"].items()}
for folder in [Path(w["language_materials"]), Path(w["library_root"])]:
    for p in folder.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            protected[str(p)] = sha(p)
for p in [
    BASE / "native-rpent/workbench.json",
    BASE / "native-rpent/start-workbench.sh",
    Path("/home/zwy/work/harnessvla/rpent/planner/api_loop.py"),
    ROOT / "a/workbench.json",
    ROOT / "a/expected-selected-tools.json",
    ROOT / "a/start.sh",
    ROOT / "trace_workbench.py",
]:
    protected[str(p)] = sha(p)
save(
    ROOT / "invariants.json",
    {
        "source_hashes": protected,
        "original_config": api("/api/session/config"),
        "original_server_id": state["server_id"],
    },
)
save(
    ROOT / "READY.json",
    {
        "approved_task": 0,
        "seed": 0,
        "maximum_episodes": 1,
        "network_changes_by_experiment": False,
    },
)
save(ROOT / "status.json", {"phase": "prepared", "planned": 1, "completed": 0})
print(
    json.dumps(
        {
            "root": str(ROOT),
            "port": port,
            "protected_files": len(protected),
            "config": plan["config"],
        }
    )
)
