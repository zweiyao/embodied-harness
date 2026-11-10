# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Verify approved material/tool parity and two idle isolated workbenches."""

import json
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import robots.libero.eef_control as eef_module
import robots.libero.research.manual as manual_module
import robots.libero.research.orientation as orientation_module
import robots.libero.research.placement as placement_module
from metrics import ACTIONS, analyze
from robots.libero.prompt_bundle import system_prompt, user_prompt
from robots.libero.research.language_materials import freeze_materials
from robots.libero.research.library import Library, Sandbox
from robots.libero.research.manual import availability_prompt
from run_batch import PLAN, ROOT, api, classify, save, unchanged

import rpent.dashboard.workbench as workbench_module
import rpent.memory.manager as memory_module
import rpent.tools.common as common_module
import rpent.utils.config as config_module
from rpent.dashboard.workbench import native_catalog
from rpent.memory import MemoryManager
from rpent.prompt.utils import format_prompt
from rpent.tools.common import CommonTools
from rpent.utils.config import get_repo_root

assert (ROOT / "READY.json").is_file(), "Wait for coordinating agent READY"
report = {"passed": False, "environment_actions": 0}
source = Path(PLAN["runtime_source"]).resolve()
assert source != Path("/home/zwy/work/harnessvla")
assert all(
    Path(module.__file__).resolve().is_relative_to(source)
    for module in [
        eef_module,
        manual_module,
        placement_module,
        orientation_module,
        workbench_module,
        memory_module,
        common_module,
        config_module,
    ]
)
assert (
    PLAN["source_handoff"]["validation_passed"]
    and PLAN["source_handoff"]["simulator_probe_passed"]
)
report["runtime_source"] = str(source)
report["isolated_source_imports_verified"] = True
assert get_repo_root() == source
assert str(get_repo_root()) == PLAN["memory_path_base"]
report["memory_path_base"] = str(get_repo_root())
report["path_environment"] = {"RPENT_REPO_ROOT": os.environ.get("RPENT_REPO_ROOT")}
motion = next(t for t in native_catalog() if t["name"] == "translate_to")
assert motion["category"] == "control"
assert motion["version"] == PLAN["native_motion_version"]
assert set(motion["parameters"]["properties"]) == {"xyz"}
assert "translate_to" in ACTIONS and "native:translate_to" in PLAN["config"]["tools"]
assert "Use translate_to for position-only moves" in availability_prompt([motion])
report["motion_catalog_and_selected_guidance"] = True
catalog = {t["name"]: t for t in native_catalog()}
placements = [catalog[name] for name in ["preview_placement", "align_placement"]]
assert {t["name"]: t["version"] for t in placements} == PLAN[
    "native_placement_versions"
]
preview, align = placements
assert preview["category"] == "perception" and align["category"] == "control"
assert set(preview["parameters"]["required"]) == {
    "step",
    "camera",
    "held_feature",
    "target_region",
    "plane_samples",
}
assert set(align["parameters"]["properties"]) == {"preview_id"}
assert "preview_placement selects a visible target region" in availability_prompt(
    placements
)
assert "preview_placement selects a visible target region" not in availability_prompt(
    [motion]
)
assert "align_placement" in ACTIONS
report["placement_catalog_and_selected_guidance"] = {
    "passed": True,
    "versions": PLAN["native_placement_versions"],
}
orientation = catalog["rotate_axis"]
assert orientation["version"] == PLAN["native_orientation_version"]
assert orientation["category"] == "control"
assert set(orientation["parameters"]["properties"]) == {"axis", "angle_rad"}
assert set(orientation["parameters"]["required"]) == {"axis", "angle_rad"}
assert orientation["parameters"]["properties"]["axis"]["enum"] == ["x", "z"]
assert "Use rotate_axis for relative world-axis rotation" in availability_prompt(
    [orientation]
)
assert "Use rotate_axis for relative world-axis rotation" not in availability_prompt(
    placements
)
assert "rotate_axis" in ACTIONS
report["orientation_catalog_and_selected_guidance"] = {
    "passed": True,
    "version": orientation["version"],
}
with tempfile.TemporaryDirectory(prefix="qwen-motion-metrics-") as temp:
    fixture = Path(temp) / "events.jsonl"
    for step in [0, 1]:
        items = [
            (
                "tool_request",
                {"name": "view_env_state", "call_id": "v", "arguments": {}},
            ),
            ("tool_response", {"name": "view_env_state", "call_id": "v", "result": {}}),
            (
                "tool_request",
                {
                    "name": "translate_to",
                    "call_id": "m",
                    "arguments": {"xyz": [0, 0, 0]},
                },
            ),
            (
                "tool_response",
                {
                    "name": "translate_to",
                    "call_id": "m",
                    "result": {"step": step, "log": {"command": "translate_to"}},
                },
            ),
        ]
        fixture.write_text(
            "".join(
                json.dumps(
                    {
                        "kind": kind,
                        "payload": payload,
                        "time": f"2026-11-09T00:00:0{i}+00:00",
                    }
                )
                + "\n"
                for i, (kind, payload) in enumerate(items)
            )
        )
        measured = analyze(temp, audit=False)
        assert measured["has_action_call"] and measured["action_calls"] == 1
        assert measured["first_action_tool"] == "translate_to"
        assert measured["before_action_calls"] == 1
        assert measured["first_action_confirmed_executed"] is (step > 0)
report["motion_metrics_fixture"] = {
    "passed": True,
    "limitation": "The legacy execution indicator is a recorded-step/command proxy, not measured displacement or holding.",
}
removed = {"move_to", "move_pose", "move_eef", "rotate_wrist", "rotate_pitch"}
assert len(PLAN["tool_names"]) == 18 and not removed.intersection(PLAN["tool_names"])
assert "native:move_eef" not in PLAN["config"]["tools"]
assert "sensor_container_geometry" not in PLAN["tool_names"]
assert PLAN["tool_versions"] == [
    "553831b20799170badced4a5ea5dde8ef75d8e38a50527ca7debe01cb7fdf5bf"
]
checks = subprocess.run(
    [
        "python",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        str(source / "tests/unit_tests/robots/libero/test_eef_control.py"),
        str(source / "tests/unit_tests/robots/libero/research/test_manual.py"),
        "-k",
        "rotate_axis or test_workbench_selection_enables_only_its_own_environment or test_native_controls_unchanged_and_disabled_tool_rejected or test_default_selection_and_prompt_do_not_enable_eef",
    ],
    cwd=source,
    capture_output=True,
    text=True,
)
(ROOT / "selection-check.log").write_text(checks.stdout + checks.stderr)
assert checks.returncode == 0, "R selection/controller registration checks failed"
report["orientation_selection_checks"] = {
    "passed": True,
    "tools": 18,
    "removed": sorted(removed),
    "eef_wrapper_expected": True,
    "log": "selection-check.log",
}
report["materials"] = []
for lane_name, settings in PLAN["lanes"].items():
    material = Path(settings["materials"])
    manifest = json.loads((material / "manifest.json").read_text())
    assert manifest["version"] == settings["material_version"]
    with tempfile.TemporaryDirectory(prefix="qwen-ce-material-") as temp:
        variables = {
            "suite": "libero_10_task",
            "task": 4,
            "seed": 0,
            "output_dir": temp,
        }
        freeze_materials(material, temp, variables)
        system = format_prompt(system_prompt(variables), variables=variables)
        user = format_prompt(user_prompt(variables), variables=variables)
        assert "{{" not in system + user
        memory_root = Path(variables["memory_dir"])
        assert str(memory_root / "MEMORY.md") in system + user
        import re

        links = re.findall(r"\]\(([^)]+)\)", (memory_root / "MEMORY.md").read_text())
        assert links and all((memory_root / link).is_file() for link in links)
        file_tools = CommonTools(memory=MemoryManager(memory_root))
        for link in links:
            result = file_tools.read_text_file(path=str(memory_root / link))
            assert result.data["content"] == (material / "memory" / link).read_text()
            try:
                file_tools.write_text_file(path=str(memory_root / link), content="test")
            except PermissionError:
                pass
            else:
                raise AssertionError("Published memory must stay read-only")
    report["materials"].append(
        {
            "lane": lane_name,
            "version": manifest["version"],
            "files": len(manifest["files"]),
            "actual_reads": len(links),
            "write_denials": len(links),
            "freeze_render_links": True,
        }
    )
assert classify(
    {"status": "timeout", "error": "planner timed out after 600s", "elapsed_s": 601}
) == ("budget_timeout", False)
assert classify(
    {"status": "timeout", "error": "planner timed out after 600s", "elapsed_s": 2}
) == ("unexpected", None)
assert classify({"status": "error", "error": "network failed"}) == ("unexpected", None)
assert classify({"status": "completed", "environment_success": True}) == (
    "task_result",
    True,
)
assert classify({"status": "budget_exhausted", "environment_success": False}) == (
    "task_result",
    False,
)
report["classification_checks"] = 5
row, col = np.mgrid[:256, :256]
world = np.stack(
    [(col - 128) / 1000, (row - 128) / 1000, np.full((256, 256), 0.13)], axis=-1
)
frame = {
    "step": 7,
    "proprio": {"robot0_eef_pos": [0.01, 0.02, 0.25]},
    "cameras": {
        "agentview": {
            "high": {"world": world, "rgb": np.zeros((256, 256, 3), dtype=np.uint8)}
        }
    },
}
sandbox = Sandbox("embodied-sensor:pilot")
library = Library(Path(PLAN["candidate_library"]))
checks = []
for version in PLAN["tool_versions"]:
    (tool,) = library.load(version)
    if tool["name"] == "sensor_patch_batch":
        result = sandbox.run(
            tool, {"points": [[128 / 255, 128 / 255]], "step": 7}, [frame]
        )
        np.testing.assert_allclose(
            result["patches"][0]["world_median_xyz"], [0, 0, 0.13]
        )
        np.testing.assert_allclose(
            result["patches"][0]["eef_to_patch_xyz"], [-0.01, -0.02, -0.12]
        )
        from jsonschema import ValidationError

        try:
            sandbox.run(tool, {"points": [[0.5, 0.5]], "radius": 0}, [frame])
        except ValidationError:
            pass
        else:
            raise AssertionError(
                "radius=0 must be rejected by the actual sandbox schema"
            )
        missing_params = {"points": [[0.5, 0.5]], "step": 8}
    else:
        raise AssertionError("Only old sensor_patch_batch is selected")
    assert "error" in sandbox.run(tool, missing_params, [frame])
    checks.append(
        {
            "name": tool["name"],
            "version": version,
            "docker_execution": True,
            "missing_step_rejected": True,
        }
    )
report["published_tool_checks"] = checks
unchanged()
started = []
try:
    for name, lane in PLAN["lanes"].items():
        subprocess.run(["bash", "-n", str(ROOT / name / "start.sh")], check=True)
        subprocess.run(
            [
                "systemd-run",
                "--user",
                "--unit=" + lane["unit"],
                "--property=WorkingDirectory=/home/zwy/work/embodied_harness",
                "--property=TimeoutStopSec=45",
                "/bin/bash",
                str(ROOT / name / "start.sh"),
            ],
            check=True,
        )
        started.append(lane)

    def prepare(name):
        lane = PLAN["lanes"][name]
        for _ in range(60):
            try:
                assert (
                    api(lane["port"], "/api/session/state")["session_state"] == "ready"
                )
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError(name + " did not become ready")
        payload = {
            k: v
            for k, v in PLAN["config"].items()
            if k
            in [
                "model_profile",
                "tools",
                "max_turns",
                "max_tokens",
                "planner_timeout_s",
            ]
        }
        api(lane["port"], "/api/session/config", payload)
        assert api(lane["port"], "/api/session/config") == PLAN["config"]
        check = api(
            lane["port"],
            "/api/llm/check",
            {"model_profile": PLAN["config"]["model_profile"]},
            timeout=90,
        )
        assert check["ok"]
        pid = subprocess.check_output(
            ["systemctl", "--user", "show", lane["unit"], "-p", "MainPID", "--value"],
            text=True,
        ).strip()
        env = dict(
            x.split("=", 1)
            for x in Path("/proc/" + pid + "/environ").read_bytes().decode().split("\0")
            if "=" in x
        )
        assert not any(
            k in env
            for k in [
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ]
        )
        actual_memory_base = (
            Path(env["RPENT_REPO_ROOT"]).expanduser().resolve()
            if env.get("RPENT_REPO_ROOT")
            else source
        )
        assert str(actual_memory_base) == PLAN["memory_path_base"]
        state = api(lane["port"], "/api/session/state")
        assert not state["operator"]["active"] and state["pending_task"] is None
        return {
            "lane": name,
            "server_id": state["server_id"],
            "port": lane["port"],
            "config_matches": True,
            "memory_path_base": str(actual_memory_base),
            "repo_root_override": env.get("RPENT_REPO_ROOT"),
            "proxy_absent": True,
            "connectivity_ok": True,
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(prepare, n) for n in PLAN["lanes"]]
        report["lanes"] = [f.result() for f in futures]
    assert len({r["server_id"] for r in report["lanes"]}) == len(PLAN["lanes"])
    unchanged()
    report["passed"] = True
except Exception:
    for lane in started:
        subprocess.run(["systemctl", "--user", "stop", lane["unit"]])
    raise
finally:
    save(ROOT / "preflight.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
