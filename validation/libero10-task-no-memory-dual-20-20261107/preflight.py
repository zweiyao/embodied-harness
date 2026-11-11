# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Validate approved materials, statistics and both idle model workbenches."""

import json
import py_compile
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from metrics import analyze
from run_batch import PLAN, ROOT, api, classify, save, unchanged

from robots.libero.prompt_bundle import system_prompt, user_prompt
from robots.libero.research.language_materials import freeze_materials
from rpent.prompt.utils import format_prompt

report = {"passed": False, "material_tests": {}, "statistics_tests": {}}
for name in ["metrics.py", "run_batch.py", "cleanup.py"]:
    py_compile.compile(str(ROOT / name), doraise=True)
materials = Path(PLAN["materials"])
old = materials.parent / "v1"
with tempfile.TemporaryDirectory(prefix="empty-memory-preflight-") as directory:
    temp = Path(directory)
    variables = {
        "suite": "libero_10_task",
        "task": 0,
        "seed": 0,
        "output_dir": str(temp),
    }
    freeze_materials(materials, temp, variables)
    for name in ["system.md", "user.md", "guide.md"]:
        assert (materials / name).read_bytes() == (old / name).read_bytes()
    assert [
        p.relative_to(temp / "language-materials/memory").as_posix()
        for p in (temp / "language-materials/memory").rglob("*")
        if p.is_file()
    ] == ["MEMORY.md"]
    rendered = format_prompt(
        system_prompt(variables), variables=variables
    ) + format_prompt(user_prompt(variables), variables=variables)
    assert (
        "{{" not in rendered
        and str(temp / "language-materials/memory/MEMORY.md") in rendered
    )
    report["material_tests"] = {
        "three_original_texts_identical": True,
        "empty_index_only": True,
        "rendered_without_placeholders": True,
    }

    def event(kind, payload):
        return {"kind": kind, "time": "2026-11-07T00:00:00+00:00", "payload": payload}

    def request(n, name):
        return event("tool_request", {"name": name, "call_id": str(n), "arguments": {}})

    def check(events):
        (temp / "events.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events)
        )
        return analyze(temp)

    m = check(
        [
            request(0, "view_env_state"),
            request(1, "read_image"),
            request(2, "back_project"),
            request(3, "move_to"),
        ]
    )
    assert (
        m["before_action_calls"] == 3
        and m["before_action_observations"] == 2
        and m["before_action_perception"] == 1
        and m["first_action_model_request"] is None
    )
    m = check([request(0, "view_env_state"), request(1, "read_text_file")])
    assert m["before_action_calls"] is None and not m["has_action_call"]
    m = check(
        [
            request(0, "move_to"),
            event(
                "tool_response",
                {
                    "name": "move_to",
                    "call_id": "0",
                    "result": {"error": "bad arguments"},
                },
            ),
        ]
    )
    assert not m["first_action_confirmed_executed"] and m["tool_error_responses"] == 1
    m = check(
        [
            event("model_request", {}),
            request(0, "view_env_state"),
            request(1, "segment"),
            request(2, "move_to"),
        ]
    )
    assert m["first_action_model_request"] == 1 and m["before_action_calls"] == 2
    m = check(
        [
            request(0, "read_text_file"),
            event(
                "tool_response",
                {
                    "name": "read_text_file",
                    "call_id": "0",
                    "result": {
                        "path": "/tmp/outside-experience.md",
                        "content": "old experience",
                    },
                },
            ),
        ]
    )
    assert not m["memory_audit_passed"]
    report["statistics_tests"]["synthetic_cases_passed"] = 5
assert classify(
    {"status": "timeout", "error": "planner timed out after 1500s", "elapsed_s": 1500}
) == ("budget_timeout", False)
assert classify(
    {"status": "timeout", "error": "Codex SDK timed out after 1500s", "elapsed_s": 1500}
) == ("budget_timeout", False)
assert classify({"status": "error", "error": "network failed", "elapsed_s": 2}) == (
    "unexpected",
    None,
)
report["classification_cases_passed"] = 3
base = ROOT.parent
qrow = json.loads(
    (base / "qwen-minimal-v1-candidate8-20261107/results.json").read_text()
)[0]
a = analyze(qrow["path"], audit=False)
assert (
    a["before_action_calls"] == 12
    and a["before_action_observations"] == 1
    and a["first_action_model_request"] == 13
)
arow = next(
    r
    for r in json.loads(
        (base / "libero10-task-astra-50-20261105/resume32/results.json").read_text()
    )
    if r.get("classification") != "unexpected"
)
a = analyze(arow["path"], audit=False)
assert (
    a["has_action_call"]
    and a["first_action_model_request"] is None
    and a["before_action_observations"] == 1
)
report["statistics_tests"]["qwen_and_astra_historical_replay_passed"] = True
unchanged()
started = []
try:
    for name, lane in PLAN["lanes"].items():
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
        for _ in range(90):
            try:
                assert (
                    api(lane["port"], "/api/session/state")["session_state"] == "ready"
                )
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError(name + " dashboard unavailable")
        payload = {
            k: v
            for k, v in lane["config"].items()
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
        actual = api(lane["port"], "/api/session/config")
        assert actual == lane["config"], (name, "configuration mismatch")
        check = api(
            lane["port"],
            "/api/llm/check",
            {"model_profile": lane["config"]["model_profile"]},
            timeout=150,
        )
        safe = {
            k: check.get(k)
            for k in ["ok", "status", "detail", "checked_at", "latency_s"]
        }
        save(ROOT / name / "connectivity.json", safe)
        assert check["ok"], name + " connection check failed; no experiment dispatched"
        pid = subprocess.check_output(
            ["systemctl", "--user", "show", lane["unit"], "-p", "MainPID", "--value"],
            text=True,
        ).strip()
        env = dict(
            x.split(b"=", 1)
            for x in Path("/proc/" + pid + "/environ").read_bytes().split(b"\0")
            if b"=" in x
        )
        assert all(
            env.get(k.encode(), b"").decode() == v for k, v in lane["network"].items()
        )
        return {
            "lane": name,
            "config": actual,
            "connection": safe,
            "network_verified": True,
            "server_id": api(lane["port"], "/api/session/state")["server_id"],
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(prepare, name) for name in PLAN["lanes"]]
        report["lanes"] = [f.result() for f in futures]
    assert report["lanes"][0]["server_id"] != report["lanes"][1]["server_id"]
    unchanged()
    report["passed"] = True
except Exception as exc:
    report["error"] = str(exc)
    for lane in started:
        subprocess.run(["systemctl", "--user", "stop", lane["unit"]])
    raise
finally:
    save(ROOT / "preflight.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
