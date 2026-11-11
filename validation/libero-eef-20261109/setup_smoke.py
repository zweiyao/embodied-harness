# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Prepare one opt-in workbench using the existing Max thinking profile."""

import json
import shutil
import socket
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
ROOT = BASE / "validation/libero-eef-20261109"
LANE = ROOT / "smoke"
SOURCE = Path("/home/zwy/work/harnessvla")
OLD = BASE / "experiments/qwen-max-v3-screen3-20261107/a"

LANE.mkdir(exist_ok=False)
shutil.copytree(OLD / "libero-config", LANE / "libero-config")
config = json.loads((OLD / "workbench.json").read_text())
config["runs_root"] = str(LANE / "runs")
(LANE / "workbench.json").write_text(json.dumps(config, indent=2) + "\n")
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
tools = [
    "finish",
    "view_env_state",
    "move_eef",
    "read_text_file",
    "list_dir",
    "read_image",
]
plan = {
    "port": port,
    "unit": "rpent-libero-eef-smoke-20261109.service",
    "suite": "libero_10_task",
    "task": 0,
    "seed": 0,
    "model_profile": "qwen3.8-max",
    "reasoning_effort": "medium",
    "max_turns": 8,
    "max_tokens": 16384,
    "planner_timeout_s": 600,
    "tools": ["native:" + t for t in tools],
    "language_materials": config["language_materials"],
    "purpose": "One integration smoke, not a success-rate evaluation",
}
(LANE / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
script = f"""#!/bin/bash
set -euo pipefail
cd {BASE}
source {SOURCE}/local-setup/activate.sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export RPENT_REPO_ROOT={ROOT}/checkout PYTHONPATH={ROOT}/checkout HF_HUB_OFFLINE=1
export LIBERO_CONFIG_PATH={LANE}/libero-config
export RPENT_WORKBENCH={LANE}/workbench.json
unset RPENT_TOOL_CATALOG
exec python -m rpent.cli.main --robot libero --libero-type pro --enable-eef-control --dashboard --dashboard-host 127.0.0.1 --dashboard-port {port} --dashboard-language zh-cn --planner api --model openai-chat:qwen3.8-max --reasoning-effort medium --memory-profile local --memory-dir {config["language_materials"]}/memory --vla-endpoint http://127.0.0.1:49337 --sam3-endpoint http://127.0.0.1:37867 --max-turns 8 --max-tokens 16384 --planner-timeout-s 600 --output-dir {LANE}/runs/session
"""
(LANE / "start.sh").write_text(script)
print(json.dumps(plan))
