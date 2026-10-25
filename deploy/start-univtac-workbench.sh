#!/usr/bin/env bash
set -euo pipefail
umask 077

workspace=/home/zwy/work/embodied_harness
repo=/home/zwy/work/harnessvla
cd "$workspace"
source "$repo/local-setup/activate.sh"

# The planner uses RPent's environment; the simulator uses its own wrapper.
unset MUJOCO_GL PYOPENGL_PLATFORM XLA_PYTHON_CLIENT_PREALLOCATE
unset LIBERO_CONFIG_PATH LIBERO_PRO_ASSET_PATH PI05_CHECKPOINT_PATH
unset SAM3_CHECKPOINT_PATH OPENPI_DATA_HOME
export PYTHONPATH="$repo"
export RPENT_WORKBENCH="$workspace/native-univtac/workbench.json"
export DISPLAY=:1
export HTTP_PROXY=http://127.0.0.1:7900 HTTPS_PROXY=http://127.0.0.1:7900
export ALL_PROXY=http://127.0.0.1:7900
export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" all_proxy="$ALL_PROXY"
export NO_PROXY=localhost,127.0.0.1,::1,10.162.250.228
export no_proxy="$NO_PROXY"

exec "$repo/.venv/bin/python" -m rpent.cli.main \
  --robot univtac \
  --univtac-root "$workspace/external/UniVTAC" \
  --univtac-python "$workspace/external/isaac-rtx-compat/univtac-python" \
  --dashboard --dashboard-host 127.0.0.1 --dashboard-port 8093 \
  --dashboard-language zh-cn \
  --planner codex --model gpt-6-astra --reasoning-effort low \
  --suite univtac --task 0 --seed 2 \
  --pilot-root "$workspace/experiments/tactile-pilot-20261025" \
  --pilot-cell dev-03 \
  --max-turns 60 --max-tokens 8192 --planner-timeout-s 3600 \
  --output-dir "$workspace/univtac-runs/session-$(date -u +%Y%m%d-%H%M%S)-$$"
