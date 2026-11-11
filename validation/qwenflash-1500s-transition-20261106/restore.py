# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
import json
import pathlib
import subprocess
import time
import urllib.request

r = pathlib.Path(__file__).resolve().parent


def api(path, data=None):
    req = urllib.request.Request(
        "http://127.0.0.1:8092" + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=15))


assert api("/api/session/state")["session_state"] == "ready", (
    "Active episode: leave bypass until safe restoration"
)
p = pathlib.Path((r / "dropin-path.txt").read_text())
p.unlink(missing_ok=True)
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
subprocess.run(
    ["systemctl", "--user", "restart", "embodied-manual-workbench.service"], check=True
)
for _ in range(60):
    try:
        api("/api/session/config", json.loads((r / "restore-config.json").read_text()))
        break
    except Exception:
        time.sleep(2)
else:
    raise RuntimeError("Restored service did not become ready")
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
e = dict(
    x.split(b"=", 1)
    for x in pathlib.Path("/proc/" + pid + "/environ").read_bytes().split(b"\0")
    if b"=" in x
)
expected = json.loads((r / "original-network.json").read_text())
assert all(e.get(k.encode(), b"").decode() == v for k, v in expected.items())
(r / "restoration.json").write_text(
    json.dumps(
        {"restored": True, "original_no_proxy_verified": True, "time": time.time()}
    )
)
