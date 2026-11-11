# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Repeat the frozen three-cell Flash screen with the existing Max profile."""

import copy
import hashlib
import json
import shutil
import socket
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path("/home/zwy/work/embodied_harness")
OLD = BASE / "experiments/qwen-evidence-v3-screen3-retry-20261107"
assert not (ROOT / "plan.json").exists(), "Never overwrite a prepared batch"
old_plan = json.loads((OLD / "plan.json").read_text())
old_invariants = json.loads((OLD / "invariants.json").read_text())
assert json.loads((OLD / "status.json").read_text())["phase"] == "completed"
assert json.loads((OLD / "cleanup.json").read_text())["passed"]
assert all(
    hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
    for p, h in old_invariants["source_hashes"].items()
), "Independent changes require inspection"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path):
    return json.load(opener.open("http://127.0.0.1:8092" + path, timeout=15))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


state = api("/api/session/state")
assert state["session_state"] == "ready" and not state["operator"]["active"]
original_config = api("/api/session/config")
wb = json.loads((BASE / "native-rpent/workbench.json").read_text())
chosen = next(x for x in wb["models"] if x["id"] == "qwen3.8-max")
flash = next(x for x in wb["models"] if x["id"] == "qwen3.8-flash")
assert chosen["planner"] == "api" and chosen["reasoning_effort"] == "none"
assert chosen["base_url"] == flash["base_url"]
chosen = {**chosen, "reasoning_effort": "medium"}
plan = copy.deepcopy(old_plan)
plan["approval"] = (
    "User requested Qwen Max with thinking enabled for the just-completed three tasks; preserve the latest 600-second conditions"
)
plan["config"].update(
    model_profile=chosen["id"], model=chosen["model"], reasoning_effort="medium"
)
plan["comparison"] = (
    "Same frozen material/tools/tasks/seeds/budgets as the latest Flash screen; model plus thinking enabled; small development sample"
)
plan["reference_root"] = str(OLD)
plan["lanes"] = {}
ports = set()
for name, old_lane in old_plan["lanes"].items():
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
    script = (OLD / name / "start.sh").read_text()
    script = (
        script.replace(str(OLD), str(ROOT))
        .replace(
            "--dashboard-port " + str(old_lane["port"]), "--dashboard-port " + str(port)
        )
        .replace(
            "--model openai-chat:qwen3.8-flash",
            "--model " + chosen["model"] + " --reasoning-effort medium",
        )
    )
    assert "qwen3.8-flash" not in script
    assert (
        "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy"
        in script
    )
    (lane / "start.sh").write_text(script)
    plan["lanes"][name] = {
        **old_lane,
        "port": port,
        "unit": f"rpent-{ROOT.name}-{name}.service",
    }
assert {
    k: v
    for k, v in plan["config"].items()
    if k not in ["model", "model_profile", "reasoning_effort"]
} == {
    k: v
    for k, v in old_plan["config"].items()
    if k not in ["model", "model_profile", "reasoning_effort"]
}
for key in ["materials", "material_version", "tool_versions", "trials", "total"]:
    assert plan[key] == old_plan[key]
save(ROOT / "plan.json", plan)
save(
    ROOT / "invariants.json",
    {
        **old_invariants,
        "original_config": original_config,
        "original_server_id": state["server_id"],
    },
)
save(ROOT / "status.json", {"phase": "prepared", "completed": 0, "planned": 3})
save(
    ROOT / "parity.json",
    {
        "passed": True,
        "changed_config_keys": ["model", "model_profile", "reasoning_effort"],
        "reference_root": str(OLD),
        "materials_and_tools_identical": True,
        "protected_files": len(old_invariants["source_hashes"]),
        "original_core_changed": False,
        "qwen_enable_thinking": True,
        "effort_semantics": "medium maps to Qwen enable_thinking=true, not a provider-specific graded intensity",
    },
)
print(json.dumps({"prepared": True, "model": chosen["model"], "ports": sorted(ports)}))
