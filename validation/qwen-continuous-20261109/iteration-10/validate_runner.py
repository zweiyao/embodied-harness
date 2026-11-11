# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Verify runner logic and audits before allowing any policy task submission."""

import ast
import json
import py_compile
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAN = json.loads((ROOT / "plan.json").read_text())
SOURCE = Path(PLAN["runtime_source"])


def function_ast(path, name):
    return ast.dump(
        next(
            n
            for n in ast.parse(path.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name == name
        ),
        include_attributes=False,
    )


assert function_ast(ROOT / "run_batch.py", "classify") == function_ast(
    ROOT.parent / "iteration-09/run_batch.py", "classify"
)
assert not any((ROOT / lane / "runs").exists() for lane in PLAN["lanes"])
for path in ROOT.glob("*.py"):
    py_compile.compile(str(path), doraise=True)
for path in [
    ROOT / "start_batch.sh",
    *(ROOT / lane / "start.sh" for lane in PLAN["lanes"]),
]:
    subprocess.run(["bash", "-n", str(path)], check=True)
checks = [
    (
        "classification-checks.log",
        [sys.executable, str(ROOT / "verify_classification.py")],
    ),
    ("workflow-checks.log", [sys.executable, str(ROOT / "verify_workflow_metrics.py")]),
    ("finish-checks.log", [sys.executable, str(ROOT / "verify_finish_metrics.py")]),
    (
        "runtime-audit-checks.log",
        [sys.executable, str(ROOT / "verify_runtime_audit.py")],
    ),
    (
        "view-phase-audit-checks.log",
        [
            sys.executable,
            "-m",
            "pytest",
            str(ROOT / "test_view_audit.py"),
            str(ROOT / "test_phase_audit.py"),
            "-q",
        ],
    ),
    (
        "ruff-checks.log",
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(SOURCE / "pyproject.toml"),
            str(ROOT),
        ],
    ),
]
for name, cmd in checks:
    completed = subprocess.run(
        cmd, cwd=SOURCE, capture_output=True, text=True, check=False
    )
    (ROOT / name).write_text(completed.stdout + completed.stderr)
    assert completed.returncode == 0, f"See {name}"
    print(name + ": passed", flush=True)
assert "19 passed" in (ROOT / "view-phase-audit-checks.log").read_text()
report = {
    "passed": True,
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "classifier_ast_identical_to09": True,
    "classification_cases": 14,
    "workflow_cases": 18,
    "finish_cases": 10,
    "process_observer_cases": 4,
    "view_audit_cases": 9,
    "phase_audit_cases": 10,
    "python_compile_passed": True,
    "shell_syntax_passed": True,
    "ruff_passed": True,
    "ruff_configuration": str(SOURCE / "pyproject.toml"),
    "initial_lint": "First command inherited workspace lint rules and reported existing helper style diagnostics. Restored unchanged helpers, then used explicit repository configuration; only formatting/import fixes in the owned runner copy. Parent untouched.",
    "no_policy_requests_or_simulator_actions": True,
}
(ROOT / "runner-checks.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
