# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare the approved three-episode candidate in an isolated workbench."""

import hashlib
import json
import shlex
import shutil
import socket
import urllib.request
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
SOURCE = Path("/home/zwy/work/harnessvla")
ROOT = BASE / "experiments/qwen-evidence-v2-screen3-20261107"
OLD = BASE / "language-materials/qwen-minimal-v1"
MATERIALS = BASE / "language-materials/qwen-evidence-v2"
assert not (ROOT / "plan.json").exists(), "Never overwrite a prepared experiment"
assert not MATERIALS.exists(), "Never overwrite existing language materials"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def api(path):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return json.load(op.open("http://127.0.0.1:8092" + path, timeout=15))


state = api("/api/session/state")
assert state["session_state"] == "ready" and not state["operator"]["active"]
config = api("/api/session/config")
wb_path = BASE / "native-rpent/workbench.json"
workbench = json.loads(wb_path.read_text())
original_manifest = json.loads((OLD / "manifest.json").read_text())
assert original_manifest["version"] == "qwen-minimal-v1-a4a9130c693e"
assert all(
    digest(OLD / name) == value for name, value in original_manifest["files"].items()
)
shutil.copytree(OLD, MATERIALS)
(MATERIALS / "memory/libero").mkdir(exist_ok=True)
for name in ["next-action-evidence.md", "object-relative-transfer.md"]:
    shutil.copyfile(
        ROOT / "approved-memory/libero" / name, MATERIALS / "memory/libero" / name
    )
index = MATERIALS / "memory/MEMORY.md"
index.chmod(0o644)
text = index.read_text()
offset = text.index("- [")
index.write_text(
    text[:offset] + (ROOT / "index-additions.md").read_text() + "\n" + text[offset:]
)
files = {
    p.relative_to(MATERIALS).as_posix(): digest(p)
    for p in sorted(MATERIALS.rglob("*"))
    if p.is_file() and p.name != "manifest.json"
}
version = (
    "qwen-evidence-v2-"
    + hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
)
manifest = MATERIALS / "manifest.json"
manifest.chmod(0o644)
save(manifest, {"version": version, "files": files})
for p in MATERIALS.rglob("*"):
    if p.is_file():
        p.chmod(0o444)
for name in ["system.md", "user.md", "guide.md"]:
    assert (MATERIALS / name).read_bytes() == (OLD / name).read_bytes()

versions = [
    "cca2f3c424d195fe3e55896ec0fe4c54b08b9f6929fdf794cfc98595458155c3",
    "2e120f1952a10536ded83dc85a9a78506db0f6e4c80efc741b8cfa28680b0829",
]
catalog = api("/api/tools")["tools"]
ids = list(config["tools"])
assert len(ids) == 17 and all(x.startswith("native:") for x in ids)
ids += ["generated:" + v for v in versions]
selected = [next(t for t in catalog if t["id"] == i) for i in ids]
assert [t["name"] for t in selected[-2:]] == [
    "sensor_patch_batch",
    "sensor_container_geometry",
]
chosen = next(m for m in workbench["models"] if m["id"] == "qwen3.8-flash")
budget = {"max_turns": 30, "max_tokens": 16384, "planner_timeout_s": 300}
expected = {
    **budget,
    "tools": ids,
    "model_profile": "qwen3.8-flash",
    "planner": "api",
    "model": "openai-chat:qwen3.8-flash",
    "reasoning_effort": "none",
}
plan = {
    "approved": True,
    "approval": "确认接入最新草案，验证后跑3次；实验开两个环境同时跑；取消50次",
    "suite": "libero_10_task",
    "trials": [{"task": t, "seed": 0} for t in [0, 4, 8]],
    "total": 3,
    "materials": str(MATERIALS),
    "material_version": version,
    "parent_material_version": original_manifest["version"],
    "config": expected,
    "tool_names": [t["name"] for t in selected],
    "tool_versions": versions,
    "route": "remote direct; all proxy variables unset",
    "lanes": {},
    "incident_policy": "Preserve and exclude unexpected incidents; diagnose before retrying same cell. Full 300s timeout is failure.",
    "comparison": "Candidate-only three-run screen with two parallel environments; no causal gain estimate.",
}
ports = []
for name, tasks in [("a", [0, 8]), ("b", [4])]:
    lane = ROOT / name
    lane.mkdir()
    (lane / "libero-config").mkdir()
    shutil.copyfile(
        SOURCE / "local-setup/libero-config/config.yaml",
        lane / "libero-config/config.yaml",
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port not in ports
    ports.append(port)
    save(
        lane / "workbench.json",
        {
            **workbench,
            "runs_root": str(lane / "runs"),
            "language_materials": str(MATERIALS),
            "models": [chosen],
        },
    )
    unit = f"rpent-qwen-evidence-v2-{name}-20261107.service"
    plan["lanes"][name] = {
        "port": port,
        "unit": unit,
        "trials": [{"task": t, "seed": 0} for t in tasks],
    }
    command = [
        "python",
        "-m",
        "rpent.cli.main",
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
        chosen["model"],
        "--memory-profile",
        "local",
        "--memory-dir",
        str(MATERIALS / "memory"),
        "--vla-endpoint",
        "http://127.0.0.1:49337",
        "--sam3-endpoint",
        "http://127.0.0.1:37867",
        "--max-turns",
        "30",
        "--max-tokens",
        "16384",
        "--planner-timeout-s",
        "300",
        "--output-dir",
        str(lane / "runs/session"),
    ]
    script = [
        "#!/bin/bash",
        "set -euo pipefail",
        "cd " + str(BASE),
        "source " + str(SOURCE / "local-setup/activate.sh"),
        "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy",
        "export PYTHONPATH=" + str(SOURCE) + " HF_HUB_OFFLINE=1",
        "export LIBERO_CONFIG_PATH=" + str(lane / "libero-config"),
        "export RPENT_WORKBENCH=" + str(lane / "workbench.json"),
        "export RPENT_TOOL_CATALOG=" + str(BASE / "tool-catalog.json"),
        "exec " + shlex.join(command),
    ]
    (lane / "start.sh").write_text("\n".join(script) + "\n")
save(ROOT / "plan.json", plan)
protected = [
    p
    for folder in [
        SOURCE / "robots/libero",
        SOURCE / "rpent",
        BASE / "language-materials/v1",
        OLD,
        MATERIALS,
    ]
    for p in folder.rglob("*")
    if p.is_file()
    and p.suffix in [".py", ".json", ".md"]
    and "__pycache__" not in str(p)
]
protected += [
    wb_path,
    BASE / "native-rpent/start-workbench.sh",
    BASE / "tool-catalog.json",
]
protected += [BASE / "tool-library/manual" / (v + ".json") for v in versions]
save(
    ROOT / "invariants.json",
    {
        "source_hashes": {str(p): digest(p) for p in protected},
        "original_config": config,
        "original_server_id": state["server_id"],
    },
)
save(ROOT / "status.json", {"phase": "prepared", "completed": 0, "planned": 3})
print(
    json.dumps(
        {
            "version": version,
            "ports": ports,
            "tools": len(ids),
            "protected_files": len(protected),
        }
    )
)
