#!/usr/bin/env bash
# Continue only after the separately started, three-episode baseline finishes.
set -euo pipefail

experiment_dir=${1:?experiment directory required}
library_dir=${2:?tool library directory required}
while systemctl --user is-active --quiet rpent-univtac-tool-dev-baseline-20261102.service; do
  sleep 10
done
.venv/bin/python - "$experiment_dir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
assert json.loads((root / "status.json").read_text())["phase"] == "baseline_completed"
assert len(json.loads((root / "development-baseline/results.json").read_text())) == 3
PY
exec .venv/bin/python -u examples/univtac/develop_tools.py \
  --resume-baseline --output "$experiment_dir" --library "$library_dir"
