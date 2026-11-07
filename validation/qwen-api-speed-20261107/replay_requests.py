# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Call the model only; never dispatch the tool calls it returns."""

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

from probe import credentials, run_probe

parser = argparse.ArgumentParser()
parser.add_argument("--location", choices=["remote", "mac"], required=True)
parser.add_argument("--indices", default="0,4,18")
parser.add_argument("--routes", default="direct,proxy")
parser.add_argument("--nonstream", action="store_true")
parser.add_argument("--output", required=True)
args = parser.parse_args()
root = Path(__file__).parent
if args.location == "remote":
    auth = credentials()
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
        x.split("=", 1)
        for x in Path("/proc/" + pid + "/environ").read_bytes().decode().split("\0")
        if "=" in x
    )
    for key, value in env.items():
        if "proxy" in key.lower():
            os.environ[key] = value
else:
    code = "import sys,json;sys.path.insert(0,'/home/zwy/work/embodied_harness/debug/qwen-api-speed-20261107');from probe import credentials;print(json.dumps(credentials()))"
    auth = json.loads(
        subprocess.check_output(
            ["ssh", "zwy@10.162.250.228", "python3 -c " + shlex.quote(code)], text=True
        )
    )
results = []
for n, index in enumerate(map(int, args.indices.split(","))):
    path = root / f"private-request-{index}.json"
    payload = json.loads(path.read_text())
    routes = args.routes.split(",")
    if n % 2:
        routes.reverse()
    for route in routes:
        record = {
            "location": args.location,
            "request_index": index,
            "payload_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **run_probe(auth, route, not args.nonstream, payload, max_time=90),
        }
        results.append(record)
        Path(args.output).write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(record), flush=True)
