# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare an isolated two-cell initial-action phase A screen without starting any service."""

import copy
import hashlib
import json
import os
import shutil
import socket
import urllib.request
from pathlib import Path

import yaml

from rpent.dashboard.workbench import Workbench, native_catalog
from rpent.utils.config import get_repo_root

ROOT = Path(__file__).resolve().parent
BASE = Path("/home/zwy/work/embodied_harness")
OLD = BASE / "experiments/qwen-continuous-20261109/iteration-09"
PREVIOUS = OLD
MATERIAL_HANDOFF = json.loads((ROOT / "material-handoff.json").read_text())
assert MATERIAL_HANDOFF["validation_passed"]
HANDOFF = json.loads((ROOT / "source-handoff.json").read_text())
SOURCE = Path(HANDOFF["source_root"]).resolve()
assert SOURCE.is_relative_to(BASE / "validation/qwen-continuous-20261109")
assert (
    SOURCE != BASE / "validation/qwen-continuous-20261109/motion-contract-test-checkout"
)
assert HANDOFF["validation_passed"]
assert HANDOFF["initial_action_phase"] is True
assert HANDOFF["validation"]["native_and_calibrated_default_prompts_identical"]
assert SOURCE != Path("/home/zwy/work/harnessvla")
assert (
    SOURCE
    != BASE / "validation/qwen-continuous-20261109/placement-preview-test-checkout"
)
assert Path(get_repo_root.__code__.co_filename).resolve().is_relative_to(SOURCE)
assert get_repo_root() == SOURCE, "Override RPENT_REPO_ROOT after dependency activation"
source_files = {
    str((SOURCE / name).resolve()): expected
    for name, expected in HANDOFF["source_files_sha256"].items()
}
LIBRARY = BASE / "tool-library/qwen-evidence-v3"
assert not (ROOT / "plan.json").exists(), "Never overwrite a prepared experiment"
materials = {
    "a": Path(MATERIAL_HANDOFF["package_path"]),
    "b": Path(MATERIAL_HANDOFF["package_path"]),
}
assert MATERIAL_HANDOFF["source_root"] == HANDOFF["material_source_root"]
manifests = {
    k: json.loads((v / "manifest.json").read_text()) for k, v in materials.items()
}
old = json.loads((OLD / "plan.json").read_text())
assert old["runtime_source"] == HANDOFF["parent_source_root"]
assert MATERIAL_HANDOFF["selected_tool_ids"] == old["config"]["tools"]
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
    "robots/libero/research/placement.py",
    "robots/libero/research/orientation.py",
    "rpent/dashboard/workbench.py",
    "robots/libero/robot_spec.py",
]
assert all(str(SOURCE / name) in source_files for name in required_helpers)
for name, expected in source_files.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
# R control interfaces are unchanged; their prior evidence remains protected.
verification_path = SOURCE.parent / "initial-action-phase/verification.json"
verification = json.loads(verification_path.read_text())
assert verification["passed"] and verification["external_model_requests"] == 0
assert verification["simulator_actions"] == 0
assert verification["native_catalog_records_identical"] == 22
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path):
    return json.load(opener.open("http://127.0.0.1:8092" + path, timeout=15))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


state = api("/api/session/state")
assert state["session_state"] == "ready" and not state["operator"]["active"]
original_config = api("/api/session/config")
# Both lanes use the unchanged W2 package; only the initial action phase differs.
assert manifests["a"] == manifests["b"]
assert manifests["a"]["version"] == MATERIAL_HANDOFF["package_version"]
assert manifests["a"]["files"] == MATERIAL_HANDOFF["material_files_sha256"]
assert (
    hashlib.sha256((materials["a"] / "manifest.json").read_bytes()).hexdigest()
    == MATERIAL_HANDOFF["manifest_sha256"]
)
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
for previous_file in OLD.rglob("*"):
    if (
        previous_file.is_file()
        and "__pycache__" not in previous_file.parts
        and not previous_file.name.startswith(".")
    ):
        source_hashes[str(previous_file)] = hashlib.sha256(
            previous_file.read_bytes()
        ).hexdigest()
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
selection = json.loads((ROOT / "selected-diff.json").read_text())
assert (
    hashlib.sha256((OLD / "plan.json").read_bytes()).hexdigest()
    == selection["reference_plan_sha256"]
)
assert plan["config"]["tools"] == selection["before"]
assert selection["removed"] == [] and selection["added"] == []
assert selection["before"] == selection["after"]
plan["tool_versions"] = [
    "553831b20799170badced4a5ea5dde8ef75d8e38a50527ca7debe01cb7fdf5bf"
]
catalog = {t["name"]: t for t in native_catalog()}
placement_versions = {
    name: catalog[name]["version"] for name in ["preview_placement", "align_placement"]
}
assert (
    placement_versions
    == HANDOFF["placement_tool_versions"]
    == old["native_placement_versions"]
)
assert (
    catalog["rotate_axis"]["version"]
    == HANDOFF["orientation_tool_version"]
    == old["native_orientation_version"]
)
assert HANDOFF["native_motion_version"] == old["native_motion_version"]
assert catalog["translate_to"]["version"] == old["native_motion_version"]
assert plan["config"]["tools"] == selection["after"] and len(plan["tool_names"]) == 18
assert all(
    plan["config"][key] == value for key, value in selection["preserved"].items()
)
source_hashes[str(ROOT / "selected-diff.json")] = hashlib.sha256(
    (ROOT / "selected-diff.json").read_bytes()
).hexdigest()
source_hashes.update(source_files)
for name in [
    "tests/unit_tests/robots/libero/test_eef_control.py",
    "tests/unit_tests/robots/libero/research/test_manual.py",
    "tests/unit_tests/robots/libero/research/test_placement.py",
    "tests/unit_tests/robots/libero/research/test_orientation.py",
]:
    source_hashes[str(SOURCE / name)] = hashlib.sha256(
        (SOURCE / name).read_bytes()
    ).hexdigest()
for evidence in [
    str(verification_path),
    MATERIAL_HANDOFF["validation_path"],
    str(ROOT / "material-handoff.json"),
]:
    source_hashes[evidence] = hashlib.sha256(Path(evidence).read_bytes()).hexdigest()
source_hashes[str(ROOT / "source-handoff.json")] = hashlib.sha256(
    (ROOT / "source-handoff.json").read_bytes()
).hexdigest()
plan.update(
    approved=True,
    approval="Continuous user authorization covers two-cell A screen after validated source handoff. Startup requires a separate READY gate.",
    total=2,
    benchmark=benchmark,
    comparison="A on unchanged R18+W2+F+V, a=task0 and b=task4 seed0. Historical09 V parent retained; temporal and lane differences are confounds. Original C20 remains separate. No overall success-rate claim.",
    runtime_source=str(SOURCE),
    native_placement_versions=placement_versions,
    native_orientation_version=HANDOFF["orientation_tool_version"],
    selection_difference=selection,
    native_motion_version="6711255f161f2c32649b31f6c2ff8055f5c8544bfbdca507ce66fa4daac280af",
    process_working_directory=str(BASE),
    memory_path_base=str(get_repo_root()),
    source_handoff={k: v for k, v in HANDOFF.items() if k != "source_files_sha256"},
    source_handoff_sha256=hashlib.sha256(
        (ROOT / "source-handoff.json").read_bytes()
    ).hexdigest(),
    material_handoff_sha256=hashlib.sha256(
        (ROOT / "material-handoff.json").read_bytes()
    ).hexdigest(),
    material_difference=[],
    server_owned_difference={"initial_action_phase": True},
    cell_identity="full task directory path, never run_id alone across isolated roots",
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
        initial_action_phase=True,
        api_require_finish=True,
        planner_view_mode="calibrated-pair-v1",
        runs_root=str(lane / "runs"),
        language_materials=str(materials[name]),
        library_root=str(LIBRARY),
    )
    save(lane / "workbench.json", child)
    os.environ["RPENT_TOOL_CATALOG"] = str(BASE / "tool-catalog.json")
    expected_tools = Workbench(child).selection(plan["config"]["tools"])
    save(lane / "expected-selected-tools.json", expected_tools)
    source_hashes[str(lane / "expected-selected-tools.json")] = hashlib.sha256(
        (lane / "expected-selected-tools.json").read_bytes()
    ).hexdigest()
    script = (
        (OLD / name / "start.sh")
        .read_text()
        .replace(str(OLD), str(ROOT))
        .replace(old["runtime_source"], str(SOURCE))
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
    assert script.index(
        "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy"
    ) > script.index("activate.sh")
    # The selected R tool causes robot_spec to add the flag only to env_server.
    assert "--enable-eef-control" not in script
    (lane / "start.sh").write_text(script)
    plan["lanes"][name] = {
        "port": port,
        "unit": f"rpent-qwen-continuous-20261109-i10-{name}.service",
        "condition": "R18+W2+F+V+A",
        "workflow_requested": True,
        "eef_control_expected": True,
        "materials": str(materials[name]),
        "material_version": manifests[name]["version"],
        "trials": [{"task": 0 if name == "a" else 4, "seed": 0}],
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
