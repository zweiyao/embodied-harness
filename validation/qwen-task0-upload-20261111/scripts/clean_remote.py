# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

BASE = Path("/home/zwy/work/embodied_harness")
OUT = BASE / "validation/qwen-task0-upload-20261111"
OUT.mkdir(exist_ok=True)
backup = BASE / "backups/network-separation-20261111"
backup.mkdir(exist_ok=False, parents=True)
paths = [
    BASE / "run-sdk-smoke.sh",
    BASE / "native-univtac/start-workbench.sh",
    Path("/home/zwy/work/harnessvla/local-setup/dashboard.sh"),
    Path("/home/zwy/work/harnessvla/local-setup/flexiv-dashboard.sh"),
]
paths += sorted((BASE / "native-rpent").glob("*.sh"))
rows = []
patch = []
for p in paths:
    before = p.read_text()
    lines = before.splitlines(keepends=True)
    removed = [
        x
        for x in lines
        if (
            re.match(r"^(export|unset)\s+", x)
            and re.search(
                r"\b(?:HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|http_proxy|https_proxy|all_proxy|no_proxy)\b",
                x,
            )
        )
        or (x.startswith("source ") and "remote-proxy-env.sh" in x)
    ]
    after = "".join(x for x in lines if x not in removed)
    if after != before:
        # Only entire dedicated network lines are removed, not unrelated settings.
        dest = backup / str(p).lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(before)
        dest.chmod(0o600)
        assert p.read_text() == before
        p.write_text(after)
        subprocess.run(["bash", "-n", str(p)], check=True)
        patch += difflib.unified_diff(
            lines, after.splitlines(keepends=True), fromfile=str(p), tofile=str(p), n=0
        )
    rows.append(
        {
            "path": str(p),
            "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
            "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
            "removed_lines": len(removed),
            "syntax_passed": True,
        }
    )
(OUT / "launcher-cleanup.json").write_text(
    json.dumps(
        {
            "rows": rows,
            "backup": str(backup),
            "services_restarted": [],
            "scope": "current general launchers; completed experiment snapshots and backups retained",
        },
        indent=2,
    )
    + "\n"
)
(OUT / "launcher-cleanup.patch").write_text("".join(patch))
print(
    json.dumps(
        {
            "examined": len(rows),
            "changed": sum(x["removed_lines"] > 0 for x in rows),
            "removed_lines": sum(x["removed_lines"] for x in rows),
        }
    )
)
