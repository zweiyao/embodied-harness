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

from rpent.dashboard.catalog import generated_catalog
from rpent.dashboard.workbench import publish

BASE = Path("/home/zwy/work/embodied_harness")
SOURCE = Path("/home/zwy/work/harnessvla")
ROOT = Path(__file__).resolve().parent
REPAIR = "repair1" in ROOT.name
OLD = BASE / "language-materials/qwen-evidence-v2"
MATERIALS = OLD if REPAIR else BASE / "language-materials/qwen-evidence-v3"
assert not (ROOT / "plan.json").exists(), "Never overwrite a prepared experiment"
assert REPAIR or not MATERIALS.exists(), "Never overwrite existing language materials"


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
if not REPAIR:
    repair_root = ROOT.parent / "qwen-evidence-v2-repair1-20261107"
    assert json.loads((repair_root / "status.json").read_text())["phase"] == "completed"
    assert json.loads((repair_root / "cleanup.json").read_text())["passed"]
    assert not list(repair_root.glob("*/incidents.json")), (
        "Diagnose repair incident before v3"
    )

original_manifest = json.loads((OLD / "manifest.json").read_text())
assert original_manifest["version"] == "qwen-evidence-v2-56708d55045b"
assert all(
    digest(OLD / name) == value for name, value in original_manifest["files"].items()
)
if not REPAIR:
    (MATERIALS / "memory/libero").mkdir(parents=True)
    for name in ["system.md", "user.md", "guide.md"]:
        shutil.copyfile(OLD / name, MATERIALS / name)
    old_passage = "Read the language guide and the relevant experience, identify and localize the\ntarget and destination in this scene, then perform the task. Select the available\ninterfaces from their declarations; no historical interface is prescribed."
    new_passage = "Read the guide and index, then choose the next available primitive. Read experience\nfor its unresolved blocker. Resolve only the evidence that primitive needs;\ndefer later placement geometry. Follow the declared interface contracts."
    user = MATERIALS / "user.md"
    assert user.read_text().count(old_passage) == 1
    user.chmod(0o644)
    user.write_text(user.read_text().replace(old_passage, new_passage))
    import difflib

    (ROOT / "user.patch").write_text(
        "".join(
            difflib.unified_diff(
                (OLD / "user.md").read_text().splitlines(True),
                user.read_text().splitlines(True),
                fromfile="qwen-evidence-v2/user.md",
                tofile="qwen-evidence-v3/user.md",
            )
        )
    )
    for name in [
        "next-action-evidence.md",
        "object-relative-transfer.md",
        "grasp-feature-evidence.md",
    ]:
        shutil.copyfile(
            ROOT / "approved-memory/libero" / name, MATERIALS / "memory/libero" / name
        )
    shutil.copyfile(ROOT / "memory-index.md", MATERIALS / "memory/MEMORY.md")
    files = {
        p.relative_to(MATERIALS).as_posix(): digest(p)
        for p in sorted(MATERIALS.rglob("*"))
        if p.is_file()
    }
    version = (
        "qwen-evidence-v3-"
        + hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
    )
    save(MATERIALS / "manifest.json", {"version": version, "files": files})
    for p in MATERIALS.rglob("*"):
        if p.is_file():
            p.chmod(0o444)
else:
    version = original_manifest["version"]

# Publish only in a candidate library; publish() removes same-name versions.
# Never invoke it on the original library.

candidate_library = BASE / "tool-library/qwen-evidence-v3"
candidate_library.mkdir(exist_ok=True)
old_patch = "cca2f3c424d195fe3e55896ec0fe4c54b08b9f6929fdf794cfc98595458155c3"
container = "2e120f1952a10536ded83dc85a9a78506db0f6e4c80efc741b8cfa28680b0829"
if REPAIR:
    assert not list(candidate_library.iterdir()), "Do not replace a prepared library"
    for v in [old_patch, container]:
        for suffix in [".json", ".meta.json"]:
            shutil.copyfile(
                BASE / "tool-library/manual" / (v + suffix),
                candidate_library / (v + suffix),
            )
    patch_version = publish(
        candidate_library,
        json.loads((ROOT / "candidate.json").read_text()),
        {
            "source_run": "4aeed560761dad4f7217",
            "reason": "Approved radius minimum contract repair; original library preserved",
            "previous_version": old_patch,
            "input_contract": "Recorded calibrated high-resolution RGB/world/depth; radius 1–5; surface evidence only.",
        },
    )
    save(
        ROOT / "publication.json",
        {
            "version": patch_version,
            "library": str(candidate_library),
            "original_version_preserved": True,
        },
    )
else:
    publication = json.loads(
        (ROOT.parent / "qwen-evidence-v2-repair1-20261107/publication.json").read_text()
    )
    patch_version = publication["version"]
versions = [
    patch_version,
    "2e120f1952a10536ded83dc85a9a78506db0f6e4c80efc741b8cfa28680b0829",
]
catalog = api("/api/tools")["tools"] + generated_catalog(candidate_library)
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
    "approval": "User approved v3 proposal: one repaired v2 task0, then v3 tasks0/4/8 on two environments",
    "suite": "libero_10_task",
    "trials": [{"task": t, "seed": 0} for t in ([0] if REPAIR else [0, 4, 8])],
    "total": 1 if REPAIR else 3,
    "materials": str(MATERIALS),
    "material_version": version,
    "parent_material_version": original_manifest["version"],
    "config": expected,
    "tool_names": [t["name"] for t in selected],
    "tool_versions": versions,
    "route": "remote direct; all proxy variables unset",
    "repair_repeat": REPAIR,
    "candidate_library": str(candidate_library),
    "lanes": {},
    "incident_policy": "Preserve and exclude unexpected incidents; diagnose before retrying same cell. Full 300s timeout is failure.",
    "comparison": "Candidate-only three-run screen with two parallel environments; no causal gain estimate.",
}
ports = []
for name, tasks in [("a", [0])] if REPAIR else [("a", [0, 8]), ("b", [4])]:
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
            "library_root": str(candidate_library),
            "models": [chosen],
        },
    )
    unit = f"rpent-{ROOT.name}-{name}.service"
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
        BASE / "language-materials/qwen-minimal-v1",
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
protected += list((BASE / "tool-library/manual").glob("*.json"))
protected += list(candidate_library.glob("*.json"))
save(
    ROOT / "invariants.json",
    {
        "source_hashes": {str(p): digest(p) for p in protected},
        "original_config": config,
        "original_server_id": state["server_id"],
    },
)
save(
    ROOT / "status.json",
    {"phase": "prepared", "completed": 0, "planned": plan["total"]},
)
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
