# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Verify approved material/tool parity and two idle isolated workbenches."""

import json
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from robots.libero.prompt_bundle import system_prompt, user_prompt
from robots.libero.research.language_materials import freeze_materials
from robots.libero.research.library import Library, Sandbox

from rpent.memory import MemoryManager
from rpent.prompt.utils import format_prompt
from rpent.tools.common import CommonTools
from run_batch import PLAN, ROOT, api, classify, save, unchanged

report = {"passed": False, "environment_actions": 0}
material = Path(PLAN["materials"])
parent = material.parent / "qwen-evidence-v2"
new = json.loads((material / "manifest.json").read_text())["files"]
if PLAN["repair_repeat"]:
    assert material == parent
    expected_count = 217
else:
    assert set(new) == {
        "system.md",
        "user.md",
        "guide.md",
        "memory/MEMORY.md",
        *[
            "memory/" + n
            for n in [
                "next-action-evidence.md",
                "object-relative-transfer.md",
                "grasp-feature-evidence.md",
            ]
        ],
    }
    for name in [
        "system.md",
        "guide.md",
    ]:
        assert (material / name).read_bytes() == (parent / name).read_bytes()
    for name in ["next-action-evidence.md", "object-relative-transfer.md"]:
        assert (material / "memory" / name).read_bytes() == (
            parent / "memory/libero" / name
        ).read_bytes()
    expected_count = 7
assert len(new) == expected_count
with tempfile.TemporaryDirectory(prefix="qwen-v3-material-") as temp:
    variables = {"suite": "libero_10_task", "task": 0, "seed": 0, "output_dir": temp}
    freeze_materials(material, temp, variables)
    system = format_prompt(system_prompt(variables), variables=variables)
    user = format_prompt(user_prompt(variables), variables=variables)
    assert "{{" not in system + user
    assert str(Path(temp) / "language-materials/memory/MEMORY.md") in system + user
    assert "Label the intended grasp feature" not in system
    if not PLAN["repair_repeat"]:
        assert "defer later placement geometry" in user
        assert "target and destination in this scene, then perform" not in user
        import re

        index = Path(temp) / "language-materials/memory/MEMORY.md"
        links = re.findall(r"\]\(([^)]+)\)", index.read_text())
        assert len(links) == 3 and all(
            (index.parent / link).is_file() for link in links
        )
# Existence is insufficient: exercise the same memory manager and file tool as the planner.
with tempfile.TemporaryDirectory(prefix="qwen-memory-access-") as temp:
    variables = {}
    freeze_materials(material, temp, variables)
    memory_root = Path(variables["memory_dir"])
    file_tools = CommonTools(memory=MemoryManager(memory_root))
    for name in [
        "next-action-evidence.md",
        "object-relative-transfer.md",
        "grasp-feature-evidence.md",
    ]:
        result = file_tools.read_text_file(path=str(memory_root / name))
        assert result.data["content"] == (material / "memory" / name).read_text()
        try:
            file_tools.write_text_file(path=str(memory_root / name), content="test")
        except PermissionError:
            pass
        else:
            raise AssertionError("Published memory must stay read-only")
report["actual_memory_tool_reads"] = 3
report["memory_write_denials"] = 3
report["material_validation"] = {
    "file_count": len(new),
    "freeze_render_and_links": True,
    "repair_uses_unchanged_v2": PLAN["repair_repeat"],
}
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
        params = {
            "rim_points": [[80, 128], [128, 80], [176, 128], [128, 176]],
            "image_size": [256, 256],
            "step": 7,
        }
        result = sandbox.run(tool, params, [frame])
        assert result["status"] == "measured"
        np.testing.assert_allclose(result["opening"]["center_xy"], [0, 0], atol=1e-9)
        missing_params = {**params, "step": 8}
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
            env.get(k)
            for k in [
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ]
        )
        state = api(lane["port"], "/api/session/state")
        assert not state["operator"]["active"] and state["pending_task"] is None
        return {
            "lane": name,
            "server_id": state["server_id"],
            "port": lane["port"],
            "config_matches": True,
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
