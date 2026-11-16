#!/usr/bin/env bash
set -euo pipefail
umask 077
export RPENT_REPO_ROOT=/home/zwy/work/embodied_harness/checkouts/prompt-system-refactor-20261116
export RPENT_WORKBENCH=/home/zwy/work/embodied_harness/native-flexiv/workbench.json
cd "$RPENT_REPO_ROOT"
exec .venv/bin/python -m rpent.cli.main \
  --robot flexiv --dashboard --env-endpoint http://127.0.0.1:8084 \
  --dashboard-host 127.0.0.1 --dashboard-port 8083 --dashboard-language zh-cn \
  --control-mode rdk --planner codex --model gpt-6-astra --reasoning-effort high \
  --codex-analysis --codex-full-access --memory-profile local \
  --max-turns 25 --max-tokens 16384 --planner-timeout-s 3600 \
  --output-dir "/home/zwy/work/embodied_harness/flexiv-runs/session-layered-$(date -u +%Y%m%d-%H%M%S)-$$"
