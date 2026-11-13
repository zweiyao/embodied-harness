# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare the explicitly requested fixed experiment; never alter networking."""

import hashlib
import json
import shlex
import shutil
import socket
import subprocess
import urllib.request
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
ROOT = BASE / "experiments/libero-object-t-qwenflash-original-50-20261112"
SOURCE = BASE / "checkouts/libero-object-t-qwenflash-50-20261112"
MATERIALS = BASE / "language-materials/v1"
assert not ROOT.exists(), "Never overwrite an existing batch"
ROOT.mkdir(parents=True)


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    p.chmod(0o600)


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def api(path):
    with urllib.request.urlopen("http://127.0.0.1:8092" + path) as r:
        return json.load(r)


state = api("/api/session/state")
assert state["session_state"] == "ready" and state["pending_task"] is None
original = json.loads((BASE / "native-rpent/workbench.json").read_text())
profile = next(m for m in original["models"] if m["id"] == "qwen3.8-flash")
assert (
    profile["model"] == "openai-chat:qwen3.8-flash"
    and profile["reasoning_effort"] == "none"
)
manifest = json.loads((MATERIALS / "manifest.json").read_text())
assert manifest["version"] == "language-c592f23a3a324c08"
assert all(digest(MATERIALS / name) == h for name, h in manifest["files"].items())
tools = [
    "move_pose",
    "move_to",
    "pi0_doubled",
    "pi0_pick",
    "release",
    "rotate_pitch",
    "rotate_wrist",
    "set_gripper",
    "back_project",
    "read_image",
    "segment",
    "view_camera_meta",
    "view_env_state",
    "finish",
    "list_dir",
    "read_text_file",
    "write_text_file",
]
config = {
    "model_profile": profile["id"],
    "planner": "api",
    "model": profile["model"],
    "reasoning_effort": "none",
    "max_turns": 50,
    "max_tokens": 16384,
    "planner_timeout_s": 0,
    "tools": ["native:" + name for name in tools],
}
trials = [{"task": t, "seed": s} for t in range(10) for s in range(5)]
protected = {}
for folder in [
    Path("/home/zwy/work/harnessvla/rpent"),
    Path("/home/zwy/work/harnessvla/robots/libero"),
    SOURCE / "rpent",
    SOURCE / "robots/libero",
    MATERIALS,
]:
    for p in folder.rglob("*"):
        if (
            p.is_file()
            and "__pycache__" not in p.parts
            and p.suffix in [".py", ".md", ".json"]
        ):
            protected[str(p)] = digest(p)
for name in ["native-rpent/workbench.json", "native-rpent/start-workbench.sh"]:
    p = BASE / name
    protected[str(p)] = digest(p)
save(
    ROOT / "invariants.json",
    {
        "source_hashes": protected,
        "original_server_id": state["server_id"],
        "original_config": api("/api/session/config"),
        "original_public_ids": [r["id"] for r in api("/api/runs")["runs"]],
    },
)
(ROOT / "empty-library").mkdir()
lanes = {}
ports = []
for i, name in enumerate(["a", "b"]):
    lane = ROOT / name
    lane.mkdir()
    (lane / "libero-config").mkdir()
    shutil.copyfile(
        "/home/zwy/work/harnessvla/local-setup/libero-config/config.yaml",
        lane / "libero-config/config.yaml",
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert port not in ports
    ports.append(port)
    wb = {
        "runs_root": str(lane / "runs"),
        "library_root": str(ROOT / "empty-library"),
        "language_materials": str(MATERIALS),
        "models": [profile],
        "setup": {
            "models": [profile["model"]],
            "profiles": [
                p
                for p in original.get("setup", {}).get("profiles", [])
                if p.get("robot") == "libero"
            ],
        },
        "history_roots": [],
    }
    save(lane / "workbench.json", wb)
    unit = "rpent-object-t-qwenflash-" + name + "-20261112.service"
    command = [
        "python",
        "-u",
        str(ROOT / "trace_workbench.py"),
        str(lane / "http-stages.jsonl"),
        "--robot",
        "libero",
        "--libero-type",
        "pro",
        "--dashboard",
        "--dashboard-host",
        "127.0.0.1",
        "--dashboard-port",
        str(port),
        "--dashboard-language",
        "zh-cn",
        "--planner",
        "api",
        "--model",
        profile["model"],
        "--base-url",
        profile["base_url"],
        "--memory-profile",
        "local",
        "--memory-dir",
        str(MATERIALS / "memory"),
        "--vla-endpoint",
        "http://127.0.0.1:49337",
        "--sam3-endpoint",
        "http://127.0.0.1:37867",
        "--max-turns",
        "50",
        "--max-tokens",
        "16384",
        "--planner-timeout-s",
        "0",
        "--output-dir",
        str(lane / "runs/session"),
    ]
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "cd " + shlex.quote(str(BASE)),
        "source /home/zwy/work/harnessvla/local-setup/activate.sh",
        "export PYTHONPATH=" + shlex.quote(str(SOURCE)),
        "export RPENT_REPO_ROOT=" + shlex.quote(str(SOURCE)),
        "export RPENT_RLINF_ROOT=/home/zwy/work/rlinf",
        "export HF_HUB_OFFLINE=1",
        "export RPENT_WORKBENCH=" + shlex.quote(str(lane / "workbench.json")),
        "export LIBERO_CONFIG_PATH=" + shlex.quote(str(lane / "libero-config")),
        "exec " + shlex.join(command),
    ]
    (lane / "start.sh").write_text("\n".join(lines) + "\n")
    lanes[name] = {
        "port": port,
        "unit": unit,
        "trials": trials[i::2],
        "public_session": str(
            BASE
            / ("research-runs/libero-object-t-qwenflash-original-50-20261112-" + name)
        ),
    }
plan = {
    "approved_user_request": "Original RPent Object-T, every task five times, 50 interactions, no time limits; latency before batch, remote proxy off if abnormal",
    "suite": "libero_object_task",
    "total": 50,
    "tasks": list(range(10)),
    "seeds": list(range(5)),
    "configuration": config,
    "materials": str(MATERIALS),
    "material_version": manifest["version"],
    "source": str(SOURCE),
    "base_revision": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True
    ).strip(),
    "source_diff_sha256": hashlib.sha256(
        subprocess.check_output(["git", "diff"], cwd=SOURCE)
    ).hexdigest(),
    "lanes": lanes,
    "time_policy": {
        "episode_seconds": None,
        "model_http_connect_read_write_pool": None,
        "runtime_rpc_seconds": None,
        "batch_deadline": None,
        "startup_and_cleanup_checks": "Finite; not experiment performance budgets",
        "idle_retry_watchdog": False,
        "native_action_limit": 10000,
    },
    "incident_policy": "Preserve unexpected incidents, exclude from denominator, pause before retry after diagnosis; no retries for valid model/task failures",
    "network": "Inherited selected remote environment. No script changes proxies, IP family or client proxy policy.",
    "scope": "Fixed evaluation only; no autonomous optimization; no physical robot access",
}
save(ROOT / "plan.json", plan)
save(ROOT / "status.json", {"phase": "prepared", "planned": 50, "completed": 0})
print(
    json.dumps(
        {
            "root": str(ROOT),
            "ports": ports,
            "protected_files": len(protected),
            "materials": manifest["version"],
            "native_tools": len(tools),
            "trials_per_lane": [len(v["trials"]) for v in lanes.values()],
        }
    )
)
