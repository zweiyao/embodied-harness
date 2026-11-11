# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Stop only idle workbenches owned by this batch; never alter the original."""

import json
import subprocess
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent
plan = json.loads((root / "plan.json").read_text())
invariants = json.loads((root / "invariants.json").read_text())
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(port, path):
    return json.load(opener.open(f"http://127.0.0.1:{port}" + path, timeout=15))


result = {"lanes": {}}
for name, lane in plan["lanes"].items():
    try:
        active = (
            subprocess.run(
                ["systemctl", "--user", "is-active", "--quiet", lane["unit"]]
            ).returncode
            == 0
        )
        if active:
            assert (
                api(lane["port"], "/api/session/state")["session_state"] == "ready"
            ), "Active episode; leave owned service running"
            subprocess.run(["systemctl", "--user", "stop", lane["unit"]], check=True)
        result["lanes"][name] = {"stopped": True}
    except Exception as exc:
        result["lanes"][name] = {"stopped": False, "error": str(exc)}
original = api(8092, "/api/session/state")
result["original_workbench_same_server"] = (
    original["server_id"] == invariants["original_server_id"]
)
result["original_config_unchanged"] = (
    api(8092, "/api/session/config") == invariants["original_config"]
)
pid = subprocess.check_output(
    [
        "systemctl",
        "--user",
        "show",
        "embodied-manual-workbench.service",
        "-p",
        "MainPID",
        "--value",
    ],
    text=True,
).strip()
env = dict(
    x.split(b"=", 1)
    for x in Path("/proc/" + pid + "/environ").read_bytes().split(b"\0")
    if b"=" in x
)
result["original_network_unchanged"] = not any(
    env.get(k.encode())
    for k in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]
)
result["passed"] = all(v["stopped"] for v in result["lanes"].values()) and all(
    result[k]
    for k in [
        "original_workbench_same_server",
        "original_config_unchanged",
        "original_network_unchanged",
    ]
)
(root / "cleanup.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
