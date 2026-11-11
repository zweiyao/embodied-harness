# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Start an owned idle workbench, check configuration, then hand off one trial."""

import json
import subprocess
import time
from pathlib import Path

from run_batch import PLAN, ROOT, api, save, unchanged

lane = PLAN["lanes"]["a"]
assert not (ROOT / "preflight.json").exists(), "Never blindly restart this diagnostic"
unchanged()
subprocess.run(
    [
        "systemd-run",
        "--user",
        "--unit=" + lane["unit"],
        "--property=WorkingDirectory=/home/zwy/work/embodied_harness",
        "--property=KillMode=control-group",
        "/bin/bash",
        str(ROOT / "a/start.sh"),
    ],
    check=True,
)
try:
    for _ in range(60):
        try:
            state = api(lane["port"], "/api/session/state")
            assert state["session_state"] == "ready"
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError("Workbench did not become ready")
    pid = subprocess.check_output(
        ["systemctl", "--user", "show", lane["unit"], "-p", "MainPID", "--value"],
        text=True,
    ).strip()
    env = dict(
        x.split(b"=", 1)
        for x in Path("/proc/" + pid + "/environ").read_bytes().split(b"\0")
        if b"=" in x
    )
    # Inspect only. A mismatch stops the test rather than changing network settings.
    assert not any(
        k.lower() in [b"http_proxy", b"https_proxy", b"all_proxy"] and v
        for k, v in env.items()
    ), "Choose remote direct mode outside this experiment first"
    assert env[b"RPENT_REPO_ROOT"].decode() == PLAN["runtime_source"]
    payload = {
        k: v
        for k, v in PLAN["config"].items()
        if k
        in ["model_profile", "tools", "max_turns", "max_tokens", "planner_timeout_s"]
    }
    api(lane["port"], "/api/session/config", payload)
    assert api(lane["port"], "/api/session/config") == PLAN["config"]
    catalog = {t["id"]: t for t in api(lane["port"], "/api/tools")["tools"]}
    expected = json.loads((ROOT / "a/expected-selected-tools.json").read_text())
    assert [catalog[t["id"]] for t in expected] == expected
    check = api(
        lane["port"],
        "/api/llm/check",
        {"model_profile": PLAN["config"]["model_profile"]},
        timeout=90,
    )
    assert check["ok"]
    state = api(lane["port"], "/api/session/state")
    assert not state["operator"]["active"] and state["pending_task"] is None
    assert (ROOT / "http-trace.jsonl").is_file(), (
        "Telemetry must observe the real SDK probe"
    )
    unchanged()
    save(
        ROOT / "preflight.json",
        {
            "passed": True,
            "lanes": [
                {
                    "lane": "a",
                    "server_id": state["server_id"],
                    "port": lane["port"],
                    "proxy_absent": True,
                    "config_matches": True,
                }
            ],
            "task_actions_before_handoff": 0,
        },
    )
except BaseException:
    subprocess.run(["systemctl", "--user", "stop", lane["unit"]], check=True)
    raise
