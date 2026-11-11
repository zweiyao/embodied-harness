#!/bin/bash
set -euo pipefail
cd /home/zwy/work/embodied_harness
source /home/zwy/work/harnessvla/local-setup/activate.sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
study_root=/home/zwy/work/embodied_harness/experiments/qwen-continuous-20261109/iteration-05
source_root=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["runtime_source"])' "$study_root/plan.json")
export RPENT_REPO_ROOT="$source_root"
export PYTHONPATH="$source_root" HF_HUB_OFFLINE=1
exec 9>"$study_root/.launch.lock"
flock -n 9
python "$study_root/preflight.py"
python "$study_root/run_batch.py"
if python -c 'import json,sys; sys.exit(json.load(open(sys.argv[1]))["phase"] != "completed")' "$study_root/status.json"; then
    python "$study_root/audit_results.py"
fi
