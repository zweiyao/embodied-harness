# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare the approved Flash/v3 screen with one additional EEF control tool."""

import copy
import hashlib
import json
import shutil
import socket
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path("/home/zwy/work/embodied_harness")
SOURCE = Path("/home/zwy/work/harnessvla")
OLD = BASE / "experiments/qwen-evidence-v3-screen3-retry-20261107"
assert not (ROOT / "plan.json").exists(), "Never overwrite a prepared batch"
old = json.loads((OLD / "plan.json").read_text())
protected = json.loads((OLD / "invariants.json").read_text())["source_hashes"]
deployment = json.loads(
    (BASE / "validation/libero-eef-20261109/deployment.json").read_text()
)
assert json.loads((OLD / "status.json").read_text())["phase"] == "completed"
assert json.loads((OLD / "cleanup.json").read_text())["passed"]
approved_changes = {str(SOURCE / p): h for p, h in deployment["hashes"].items()}
for name, expected in protected.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == approved_changes.get(
        name, expected
    ), name
for name, expected in approved_changes.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
protected = {
    name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
    for name in set(protected) | set(approved_changes)
}
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path):
    return json.load(opener.open("http://127.0.0.1:8092" + path, timeout=15))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


state = api("/api/session/state")
assert state["session_state"] == "ready" and not state["operator"]["active"]
original_config = api("/api/session/config")
profiles = json.loads((BASE / "native-rpent/workbench.json").read_text())["models"]
chosen = next(p for p in profiles if p["id"] == "qwen3.8-flash")
assert chosen["reasoning_effort"] == "none"
plan = copy.deepcopy(old)
plan.update(
    approval="User explicitly selected tasks 0,4,8 once each with Flash, v3 experience plus move_eef, old tools retained, 600 seconds/30 requests and two environments.",
    reference_root=str(OLD),
    comparison="Existing Flash/v3 screen versus the additional selectable EEF tool and its approved conditional feedback guidance; no fresh baseline, three development cells only.",
    lanes={},
)
plan["config"]["tools"].append("native:move_eef")
plan["tool_names"].append("move_eef")
assert plan["config"]["planner_timeout_s"] == 600
assert plan["config"]["reasoning_effort"] == "none"
assert len(plan["config"]["tools"]) == 20
assert [{"task": t, "seed": 0} for t in [0, 4, 8]] == plan["trials"]
ports = set()
for name, old_lane in old["lanes"].items():
    lane = ROOT / name
    lane.mkdir()
    shutil.copytree(OLD / name / "libero-config", lane / "libero-config")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port not in ports
    ports.add(port)
    child = json.loads((OLD / name / "workbench.json").read_text())
    child.update(runs_root=str(lane / "runs"), models=[chosen])
    save(lane / "workbench.json", child)
    script = (
        (OLD / name / "start.sh")
        .read_text()
        .replace(str(OLD), str(ROOT))
        .replace(
            "--dashboard-port " + str(old_lane["port"]), "--dashboard-port " + str(port)
        )
    )
    assert (
        "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy"
        in script
    )
    # Selection enables the per-task environment flag through robot_spec.
    (lane / "start.sh").write_text(script)
    plan["lanes"][name] = {
        **old_lane,
        "port": port,
        "unit": f"rpent-{ROOT.name}-{name}.service",
    }
save(ROOT / "plan.json", plan)
save(
    ROOT / "invariants.json",
    {
        "source_hashes": protected,
        "original_config": original_config,
        "original_server_id": state["server_id"],
    },
)
save(ROOT / "status.json", {"phase": "prepared", "completed": 0, "planned": 3})
save(
    ROOT / "parity.json",
    {
        "passed": True,
        "material_version_unchanged": plan["material_version"],
        "old_tools_preserved": True,
        "added_tool": "move_eef",
        "tool_count": 20,
        "conditional_guidance": "Two approved EEF feedback sentences enabled by selection",
        "qwen_enable_thinking": False,
        "protected_files": len(protected),
        "initial_scene_parity": "Pending; task 8 previously had a fixture mismatch despite the same seed",
    },
)
print(json.dumps({"prepared": True, "ports": sorted(ports), "total": 3, "tools": 20}))
