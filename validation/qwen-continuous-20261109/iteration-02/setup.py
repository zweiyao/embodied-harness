# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare an isolated two-cell E+T screen without starting any service."""

import copy
import hashlib
import json
import shutil
import socket
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
BASE = Path("/home/zwy/work/embodied_harness")
OLD = BASE / "experiments/qwen-continuous-20261109/iteration-01"
VERSION = "eb961cc0f520a6b5f6814fad350af7a285a2725c9b50c442b8267745ad1b9195"
LIBRARY = BASE / "tool-library/qwen-continuous-20261109"
assert not (ROOT / "plan.json").exists(), "Never overwrite a prepared experiment"
materials = {
    "a": BASE / "language-materials/qwen-evidence-v4-e-readable",
    "b": BASE / "language-materials/qwen-evidence-v4-e-readable",
}
manifests = {
    k: json.loads((v / "manifest.json").read_text()) for k, v in materials.items()
}
old = json.loads((OLD / "plan.json").read_text())
prior = json.loads((OLD / "invariants.json").read_text())
for name, expected in prior["source_hashes"].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
assert json.loads((OLD / "cleanup.json").read_text())["passed"]
assert json.loads((OLD / "final-verification.json").read_text())["passed"]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path):
    return json.load(opener.open("http://127.0.0.1:8092" + path, timeout=15))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


state = api("/api/session/state")
assert state["session_state"] == "ready" and not state["operator"]["active"]
original_config = api("/api/session/config")
# Freeze unchanged E materials; only the published tool version changes.
for name in ["system.md", "user.md", "guide.md"]:
    assert (materials["a"] / name).read_bytes() == (
        materials["b"] / name
    ).read_bytes(), name
for lane, manifest in manifests.items():
    assert all(
        hashlib.sha256((materials[lane] / p).read_bytes()).hexdigest() == h
        for p, h in manifest["files"].items()
    )
config = yaml.safe_load((OLD / "a/libero-config/config.yaml").read_text())
installed_bddl = Path(old["benchmark"]["source"]).resolve()
private_bddl = ROOT / "benchmark/bddl_files"
assert not private_bddl.exists()
shutil.copytree(installed_bddl, private_bddl)
relative = "libero_10_task/KITCHEN_SCENE8_put_both_moka_pots_on_the_stove.bddl"
original = (installed_bddl / relative).read_text()
needle = "(:language put the left moka pot on the stove)"
assert original.count(needle) == 1
changed = original.replace(needle, "(:language put the right moka pot on the stove)")
(private_bddl / relative).write_text(changed)
benchmark = {
    "cohort": "libero_10_task-language-right-v1",
    "source": str(installed_bddl),
    "private_bddl": str(private_bddl),
    "changed_file": relative,
    "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
    "after_sha256": hashlib.sha256(changed.encode()).hexdigest(),
    "goal_and_init_unchanged": True,
    "benchmark_root_unchanged": config["benchmark_root"],
    "init_states_unchanged": config["init_states"],
}
source_hashes = dict(prior["source_hashes"])
for f in installed_bddl.rglob("*.bddl"):
    source_hashes[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
for f in private_bddl.rglob("*.bddl"):
    source_hashes[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
for m in materials.values():
    for f in m.rglob("*"):
        if f.is_file():
            source_hashes[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
plan = {
    k: copy.deepcopy(old[k])
    for k in [
        "suite",
        "config",
        "tool_names",
        "tool_versions",
        "candidate_library",
        "route",
        "incident_policy",
    ]
}
previous_version = old["tool_versions"][0]
assert (
    hashlib.sha256((LIBRARY / (VERSION + ".json")).read_bytes()).hexdigest()
    == "5b49561b7595b1502ef4da1fab3599d2b09942ffb1c55e5fb4c8f39a730eac22"
)
plan["tool_versions"][0] = VERSION
plan["config"]["tools"] = [
    x.replace(previous_version, VERSION) for x in plan["config"]["tools"]
]
plan["candidate_library"] = str(LIBRARY)
for f in LIBRARY.glob("*.json"):
    source_hashes[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
plan.update(
    approved=True,
    approval="User approved E to E+T development separation; coordinator authorized two cells after iteration-01 audit and cleanup. Root READY required before launch.",
    total=2,
    benchmark=benchmark,
    comparison="Development E+T versus preserved iteration-01 E on tasks4/0 seed0. Same material and budget; only sensor_patch_batch version changed. No overall success-rate claim.",
    lanes={},
)
ports = set()
for name in ["a", "b"]:
    lane = ROOT / name
    lane.mkdir()
    config_dir = lane / "libero-config"
    config_dir.mkdir()
    child_config = {**config, "bddl_files": str(private_bddl)}
    (config_dir / "config.yaml").write_text(yaml.safe_dump(child_config))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port not in ports
    ports.add(port)
    child = json.loads((OLD / name / "workbench.json").read_text())
    child.update(
        runs_root=str(lane / "runs"),
        language_materials=str(materials[name]),
        library_root=str(LIBRARY),
    )
    save(lane / "workbench.json", child)
    script = (
        (OLD / name / "start.sh")
        .read_text()
        .replace(str(OLD), str(ROOT))
        .replace(
            "--dashboard-port " + str(old["lanes"][name]["port"]),
            "--dashboard-port " + str(port),
        )
        .replace(old["candidate_library"], str(LIBRARY))
        .replace(old["lanes"][name]["materials"], str(materials[name]))
    )
    assert (
        "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy"
        in script
    )
    (lane / "start.sh").write_text(script)
    plan["lanes"][name] = {
        "port": port,
        "unit": f"rpent-qwen-continuous-20261109-i02-{name}.service",
        "condition": "E+T",
        "materials": str(materials[name]),
        "material_version": manifests[name]["version"],
        "trials": [{"task": 4 if name == "a" else 0, "seed": 0}],
    }
save(ROOT / "plan.json", plan)
save(
    ROOT / "invariants.json",
    {
        "source_hashes": source_hashes,
        "original_config": original_config,
        "original_server_id": state["server_id"],
    },
)
save(
    ROOT / "status.json",
    {"phase": "prepared_waiting_READY", "planned": 2, "completed": 0},
)
save(ROOT / "benchmark-audit.json", benchmark)
print(
    json.dumps(
        {
            "prepared": True,
            "ports": sorted(ports),
            "total": 2,
            "protected_files": len(source_hashes),
        }
    )
)
