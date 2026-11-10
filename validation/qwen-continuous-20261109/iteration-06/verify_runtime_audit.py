# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Exercise process auditing with short-lived Python fixtures, not simulators."""

import json
import shlex
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from runtime_audit import RuntimeAudit

ROOT = Path(__file__).resolve().parent
rows = []
for case in ["short_child", "missing_eef_flag", "missing_child", "cancel_observer"]:
    unit = "rpent-observer-fixture-" + uuid.uuid4().hex[:12] + ".service"
    observer = None
    with tempfile.TemporaryDirectory(prefix="rpent-observer-check-") as temporary:
        root = Path(temporary)
        lane = root / "a"
        (lane / "libero-config").mkdir(parents=True)
        source = root / "source"
        module = source / "rpent/cli"
        module.mkdir(parents=True)
        (source / "rpent/__init__.py").touch()
        (module / "__init__.py").touch()
        env_script = source / "robots/libero/env_server.py"
        env_script.parent.mkdir(parents=True)
        env_script.write_text("import time\ntime.sleep(0.5)\n")
        (module / "main.py").write_text(
            "import os,subprocess,sys,time\n"
            "from pathlib import Path\n"
            "time.sleep(0.6)\n"
            "if sys.argv[1] != 'missing_child':\n"
            " flags=[] if sys.argv[1]=='missing_eef_flag' else ['--enable-eef-control']\n"
            " subprocess.run([sys.executable,str(Path(os.environ['RPENT_REPO_ROOT'])/'robots/libero/env_server.py'),*flags,'--fixture-token','DO_NOT_RECORD_FIXTURE_SECRET'],check=True)\n"
            "time.sleep(0.3)\n"
        )
        script = lane / "start.sh"
        script.write_text(
            "#!/bin/bash\nset -euo pipefail\n"
            "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy\n"
            f"export RPENT_REPO_ROOT={shlex.quote(str(source))}\n"
            f"export PYTHONPATH={shlex.quote(str(source))}\n"
            f"export LIBERO_CONFIG_PATH={shlex.quote(str(lane / 'libero-config'))}\n"
            f"exec /usr/bin/python3 -m rpent.cli.main {case} --fixture-token DO_NOT_RECORD_FIXTURE_SECRET\n"
        )
        try:
            subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    "--unit=" + unit,
                    "--property=TimeoutStopSec=5",
                    "/bin/bash",
                    str(script),
                ],
                check=True,
                capture_output=True,
            )
            observer = RuntimeAudit(
                root, "a", {"unit": unit, "eef_control_expected": True}, source
            )
            observer.start()
            if case == "cancel_observer":
                time.sleep(0.05)
                report = observer.stop()
            else:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if (
                        subprocess.run(
                            ["systemctl", "--user", "is-active", "--quiet", unit]
                        ).returncode
                        != 0
                    ):
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("Short-lived fixture did not exit")
                report = observer.stop(
                    {"ended_at": datetime.now(timezone.utc).isoformat()}
                )
            observer = None
            assert report["observer_stopped"] and not report["observer_errors"]
            assert "DO_NOT_RECORD_FIXTURE_SECRET" not in json.dumps(report)
            if case in {"missing_child", "cancel_observer"}:
                assert (
                    report["coverage_complete"] is False
                    and not report["guard_violations"]
                )
            else:
                assert report["coverage_complete"] is True
                assert bool(report["guard_violations"]) is (case == "missing_eef_flag")
            rows.append(
                {
                    "case": case,
                    "passed": True,
                    "coverage_complete": report["coverage_complete"],
                    "guard_violations_detected": len(report["guard_violations"]),
                    "roles_captured": sorted({r["role"] for r in report["snapshots"]}),
                    "dummy_secret_excluded": True,
                }
            )
        finally:
            if observer is not None:
                observer.stop()
            if (
                subprocess.run(
                    ["systemctl", "--user", "is-active", "--quiet", unit]
                ).returncode
                == 0
            ):
                subprocess.run(
                    ["systemctl", "--user", "stop", unit],
                    check=True,
                    capture_output=True,
                )
            assert (
                subprocess.run(
                    ["systemctl", "--user", "is-active", "--quiet", unit]
                ).returncode
                != 0
            )
result = {
    "passed": True,
    "cases": rows,
    "model_requests": 0,
    "simulator_actions": 0,
    "owned_fixture_units_cleaned": True,
}
(ROOT / "runtime-audit-checks.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
