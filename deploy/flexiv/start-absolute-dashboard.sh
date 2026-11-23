#!/usr/bin/env bash
set -euo pipefail
umask 077
project_dir="${RPENT_PROJECT_ROOT:-$HOME/work/embodied_harness}"
: "${RPENT_REPO_ROOT:?Set RPENT_REPO_ROOT to the deployed Flexiv checkout}"
export RPENT_WORKBENCH="${RPENT_WORKBENCH:-$project_dir/native-flexiv/workbench.json}"
export CODEX_BIN="${CODEX_BIN:-$project_dir/validation/codex-image-window-20261119/candidate/bin/codex}"
printf '%s  %s\n' b1d54af215d6c1e03f864d17206b2ed34a479ded826b46cb31dc3f49d3313c13 "$CODEX_BIN" | sha256sum --check --status
cd "$RPENT_REPO_ROOT"
exec .venv/bin/python -m rpent.cli.main \
  --robot flexiv --dashboard --env-endpoint http://127.0.0.1:8084 \
  --dashboard-host 127.0.0.1 --dashboard-port 8083 --dashboard-language zh-cn \
  --control-mode rdk --action-mode eef_absolute --planner codex --model gpt-6-astra \
  --reasoning-effort high --codex-analysis --codex-full-access --memory-profile local \
  --max-turns 200 --max-tokens 16384 --planner-timeout-s 3600 \
  --output-dir "$project_dir/flexiv-runs/session-absolute-$(date -u +%Y%m%d-%H%M%S)-$$"
