# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Small standalone Qwen route benchmark. Never logs credentials or response text."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

REMOTE_ROOT = "/home/zwy/work/embodied_harness"
CONFIG = REMOTE_ROOT + "/native-rpent/workbench.json"


def credentials():
    config = json.loads(Path(CONFIG).read_text())
    profile = next(x for x in config["models"] if x["id"] == "qwen3.8-flash")
    return {
        "url": profile["base_url"].rstrip("/") + "/chat/completions",
        "model": profile["model"].split(":", 1)[1],
        "key": Path(profile["key_file"]).read_text().strip(),
    }


def run_probe(auth, route, stream, body=None, max_time=30):
    payload = body or {
        "model": auth["model"],
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "max_tokens": 32,
        "enable_thinking": False,
    }
    payload = {**payload, "stream": stream}
    if stream:
        payload["stream_options"] = {"include_usage": True}
    options = {
        "url": auth["url"],
        "header": "Authorization: Bearer " + auth["key"],
        "data": json.dumps(payload),
    }
    config = "\n".join(k + " = " + json.dumps(v) for k, v in options.items()) + "\n"
    command = [
        "curl",
        "--config",
        "-",
        "--header",
        "Content-Type: application/json",
        "--silent",
        "--show-error",
        "--no-buffer",
        "--connect-timeout",
        "10",
        "--max-time",
        str(max_time),
        "--write-out",
        "\n__METRICS__%{json}\n",
    ]
    if route == "direct":
        command += ["--noproxy", "*"]
    else:
        command += ["--noproxy", ""]
    start = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    process.stdin.write(config)
    process.stdin.close()
    first_content = None
    first_reasoning = None
    usage = None
    finish = None
    metrics = {}
    returned_model = None
    error_code = None
    content_chars = 0
    for line in process.stdout:
        elapsed = time.monotonic() - start
        if line.startswith("__METRICS__"):
            metrics = json.loads(line[len("__METRICS__") :])
            continue
        text = line[5:].strip() if line.startswith("data:") else line.strip()
        if not text or text == "[DONE]":
            continue
        try:
            chunk = json.loads(text)
        except json.JSONDecodeError:
            continue
        usage = chunk.get("usage") or usage
        returned_model = chunk.get("model") or returned_model
        if isinstance(chunk.get("error"), dict):
            error_code = chunk["error"].get("code")
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", choice.get("message", {}))
            if delta.get("content") or delta.get("tool_calls"):
                first_content = elapsed if first_content is None else first_content
                content_chars += len(delta.get("content") or "")
            if delta.get("reasoning_content"):
                first_reasoning = (
                    elapsed if first_reasoning is None else first_reasoning
                )
            finish = choice.get("finish_reason") or finish
    process.wait()
    # Error text can contain URLs; retain only the curl status, never raw stderr.
    process.stderr.read()
    return {
        "route": route,
        "stream": stream,
        "exit_code": process.returncode,
        "status": metrics.get("http_code"),
        "dns_s": metrics.get("time_namelookup"),
        "connect_s": metrics.get("time_connect"),
        "tls_s": metrics.get("time_appconnect"),
        "first_byte_s": metrics.get("time_starttransfer"),
        "total_s": metrics.get("time_total"),
        "first_content_s": first_content,
        "first_reasoning_s": first_reasoning,
        "usage": usage,
        "finish_reason": finish,
        "returned_model": returned_model,
        "content_chars": content_chars,
        "error_code": error_code,
        "request_bytes": len(json.dumps(payload).encode()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--location", choices=["remote", "mac"], required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--nonstream", action="store_true")
    args = parser.parse_args()
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
        # SSH transport keeps the existing credential in memory only on this Mac.
        code = "import importlib.util,json; s=importlib.util.spec_from_file_location('p','/home/zwy/work/embodied_harness/debug/qwen-api-speed-20261107/probe.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.credentials()))"
        auth = json.loads(
            subprocess.check_output(
                [
                    "ssh",
                    "zwy@10.162.250.228",
                    "python3 -c " + __import__("shlex").quote(code),
                ],
                text=True,
            )
        )
    records = []
    for repeat in range(args.repeats):
        for route in ["direct", "proxy"] if repeat % 2 == 0 else ["proxy", "direct"]:
            result = {
                "location": args.location,
                "repeat": repeat,
                **run_probe(auth, route, not args.nonstream),
            }
            records.append(result)
            Path(args.output).write_text(json.dumps(records, indent=2) + "\n")
            print(json.dumps(result), flush=True)
