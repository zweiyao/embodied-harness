# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Loopback-only model relay on a machine already authenticated with Codex.

Simulation and evaluation stay on the experiment host. The relay forwards only
sensor images / sanitized JSON to Codex, and provides no environment tools.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(60)

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/complete":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", 0))
        if not 0 < size <= 20_000_000:
            self.send_error(413)
            return
        try:
            request = json.loads(self.rfile.read(size))
            if self.server.pause_proposals and "incumbent_validation" in request.get(
                "payload", {}
            ):
                self.send_error(409, "operator pause before tool generation")
                return
            if request["model"] != self.server.model:
                raise ValueError("model does not match relay configuration")
            with tempfile.TemporaryDirectory(prefix="sensor-teacher-") as directory:
                root = Path(directory)
                output = root / "answer.json"
                command = [
                    self.server.codex,
                    "exec",
                    "--ignore-user-config",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "-C",
                    str(root),
                    "-m",
                    self.server.model,
                    "--json",
                    "-o",
                    str(output),
                ]
                command += [
                    "-c",
                    'model_provider="research-http"',
                    "-c",
                    'model_providers.research-http.name="Research HTTP"',
                    "-c",
                    "model_providers.research-http.requires_openai_auth=true",
                    "-c",
                    "model_providers.research-http.supports_websockets=false",
                ]
                for key in (
                    "shell_tool",
                    "multi_agent",
                    "apps",
                    "browser_use",
                    "computer_use",
                    "image_generation",
                    "hooks",
                ):
                    command += ["-c", f"features.{key}=false"]
                command += [
                    "-c",
                    'web_search="disabled"',
                    "-c",
                    'model_reasoning_effort="low"',
                ]
                for index, image in enumerate(request.get("images", [])):
                    path = root / f"image{index}.png"
                    path.write_bytes(base64.b64decode(image, validate=True))
                    command += ["-i", str(path)]
                prompt = (
                    request["system"]
                    + "\nUse only the supplied input. Do not call any tools.\n"
                    + json.dumps(request["payload"])
                )
                process = subprocess.run(
                    command + ["-"],
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=540,
                )
                if process.returncode or not output.exists():
                    raise RuntimeError(
                        "Codex inference failed: " + process.stderr[-1200:]
                    )
                events = [
                    json.loads(line)
                    for line in process.stdout.splitlines()
                    if line.startswith("{")
                ]
                usage = next(
                    (
                        e.get("usage", {})
                        for e in reversed(events)
                        if e.get("type") == "turn.completed"
                    ),
                    {},
                )
                # Enforce the relay's no-environment-tools protocol in the audit.
                calls = [
                    e
                    for e in events
                    if e.get("type") == "item.completed"
                    and e.get("item", {}).get("type")
                    not in {"agent_message", "reasoning", "error"}
                ]
                if calls:
                    raise RuntimeError(
                        "teacher attempted an unprovided tool: "
                        + json.dumps(calls)[:1000]
                    )
                body = json.dumps(
                    {
                        "answer": json.loads(output.read_text()),
                        "usage": usage,
                    }
                ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.send_error(502, str(exc))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18120)
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--pause-proposals", action="store_true")
    parser.add_argument("--codex", default="codex")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.model, server.codex = args.model, args.codex
    server.pause_proposals = args.pause_proposals
    server.serve_forever()


if __name__ == "__main__":
    main()
