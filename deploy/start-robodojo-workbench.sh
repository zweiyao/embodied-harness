#!/usr/bin/env bash
set -euo pipefail
umask 077

# Network selection belongs to remote-network.sh, before starting this process.
source "${1:?Usage: start-robodojo-workbench.sh runtime.env workbench.json}"
export RPENT_WORKBENCH="${2:?Supply the server-owned workbench.json}"
: "${RPENT_REPO_ROOT:?}" "${RPENT_RUNS_ROOT:?}" "${RPENT_MEMORY_DIR:?}"
cd "$RPENT_REPO_ROOT"
exec "$RPENT_REPO_ROOT/.venv/bin/python" -m rpent.cli.main \
  --robot robodojo --dashboard --dashboard-host 127.0.0.1 \
  --dashboard-port "${RPENT_DASHBOARD_PORT:-8094}" --dashboard-language zh-cn \
  --planner api --model openai-chat:qwen3.8-flash \
  --memory-profile local --memory-dir "$RPENT_MEMORY_DIR" \
  --max-turns 30 --max-tokens 4096 --planner-timeout-s 600 \
  --max-episode-steps 700 \
  --output-dir "$RPENT_RUNS_ROOT/session-$(date -u +%Y%m%d-%H%M%S)-$$"
