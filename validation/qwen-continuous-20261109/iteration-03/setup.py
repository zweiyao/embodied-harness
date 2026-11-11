# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare an isolated two-cell C+M screen without starting any service."""

import copy
import hashlib
import json
import shutil
import socket
import urllib.request
from pathlib import Path

import yaml

from rpent.utils.config import get_repo_root

ROOT = Path(__file__).resolve().parent
BASE = Path("/home/zwy/work/embodied_harness")
OLD = BASE / "experiments/qwen-continuous-20261109/iteration-01"
PREVIOUS = ROOT.parent / "iteration-02"
HANDOFF = json.loads((ROOT / "source-handoff.json").read_text())
SOURCE = Path(HANDOFF["source_root"]).resolve()
assert (
    SOURCE == BASE / "validation/qwen-continuous-20261109/motion-contract-test-checkout"
)
assert HANDOFF["validation_passed"] and HANDOFF["simulator_probe_passed"]
assert SOURCE != Path("/home/zwy/work/harnessvla")
assert Path(get_repo_root.__code__.co_filename).resolve().is_relative_to(SOURCE)
assert get_repo_root() == SOURCE, "Override RPENT_REPO_ROOT after dependency activation"
source_files = {
    str((SOURCE / name).resolve()): expected
    for name, expected in HANDOFF["source_files_sha256"].items()
}
LIBRARY = BASE / "tool-library/qwen-evidence-v3"
assert not (ROOT / "plan.json").exists(), "Never overwrite a prepared experiment"
materials = {
    "a": BASE / "language-materials/qwen-evidence-v3-readable",
    "b": BASE / "language-materials/qwen-evidence-v3-readable",
}
manifests = {
    k: json.loads((v / "manifest.json").read_text()) for k, v in materials.items()
}
old = json.loads((OLD / "plan.json").read_text())
prior = json.loads((PREVIOUS / "invariants.json").read_text())
for name, expected in prior["source_hashes"].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
assert json.loads((OLD / "cleanup.json").read_text())["passed"]
assert json.loads((OLD / "final-verification.json").read_text())["passed"]
assert json.loads((PREVIOUS / "cleanup.json").read_text())["passed"]
assert json.loads((PREVIOUS / "final-verification.json").read_text())["passed"]
assert source_files
assert all(Path(name).resolve().is_relative_to(SOURCE) for name in source_files)
required_helpers = [
    "rpent/utils/config.py",
    "rpent/memory/manager.py",
    "rpent/tools/common.py",
    "robots/libero/eef_control.py",
    "robots/libero/tools.py",
    "robots/libero/research/manual.py",
    "rpent/dashboard/workbench.py",
    "robots/libero/robot_spec.py",
]
assert all(str(SOURCE / name) in source_files for name in required_helpers)
for name, expected in source_files.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
probe = json.loads(Path(HANDOFF["probe_summary_path"]).read_text())
probe_cleanup = json.loads(Path(HANDOFF["probe_cleanup_path"]).read_text())
assert probe["passed"] and probe["model_requests"] == 0
assert Path(probe["source_root"]).resolve() == SOURCE
assert not probe["proxy_variables_present"]
assert probe_cleanup["passed"] and not probe_cleanup["remaining_owned_processes"]
assert not probe_cleanup["forced_cleanup_pids"]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path):
    return json.load(opener.open("http://127.0.0.1:8092" + path, timeout=15))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


state = api("/api/session/state")
assert state["session_state"] == "ready" and not state["operator"]["active"]
original_config = api("/api/session/config")
# Freeze unchanged C materials; add only opt-in translate_to and its selected guidance.
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
plan["config"]["tools"].append("native:translate_to")
plan["tool_names"].append("translate_to")
source_hashes.update(source_files)
for evidence in [HANDOFF["probe_summary_path"], HANDOFF["probe_cleanup_path"]]:
    source_hashes[evidence] = hashlib.sha256(Path(evidence).read_bytes()).hexdigest()
source_hashes[str(ROOT / "source-handoff.json")] = hashlib.sha256(
    (ROOT / "source-handoff.json").read_bytes()
).hexdigest()
plan.update(
    approved=True,
    approval="Preparation approved for C plus opt-in M; root READY is required after isolated source and finite simulator probe validation, before any model episode.",
    total=2,
    benchmark=benchmark,
    comparison="Development C+M versus preserved iteration-01 C on tasks4/0 seed0. Same C material and old generated tools, add translate_to and its selected two-sentence guidance. No overall success-rate claim.",
    runtime_source=str(SOURCE),
    native_motion_version="6711255f161f2c32649b31f6c2ff8055f5c8544bfbdca507ce66fa4daac280af",
    process_working_directory=str(BASE),
    memory_path_base=str(get_repo_root()),
    source_handoff={k: v for k, v in HANDOFF.items() if k != "source_files_sha256"},
    source_handoff_sha256=hashlib.sha256(
        (ROOT / "source-handoff.json").read_bytes()
    ).hexdigest(),
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
            "export PYTHONPATH=/home/zwy/work/harnessvla ",
            f"export RPENT_REPO_ROOT={SOURCE}\nexport PYTHONPATH={SOURCE} ",
        )
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
        "unit": f"rpent-qwen-continuous-20261109-i03-{name}.service",
        "condition": "C+M",
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
