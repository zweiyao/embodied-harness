# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Content-addressed perception tools; generated code only runs in Docker."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import selectors
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def validate_tools(tools: list[dict]) -> None:
    """Check declarations without importing candidate Python on the host."""
    names = set()
    for tool in tools:
        if set(tool) != {"name", "description", "parameters", "source"}:
            raise ValueError("each tool needs name, description, parameters, source")
        name = tool["name"]
        if not re.fullmatch(r"sensor_[a-z][a-z0-9_]{0,48}", name) or name in names:
            raise ValueError("tool names must be unique and start with sensor_")
        names.add(name)
        if not tool["description"] or len(tool["source"]) > 50000:
            raise ValueError("empty description or oversized source")
        schema = tool["parameters"]
        Draft202012Validator.check_schema(schema)
        if schema.get("type") != "object":
            raise ValueError("parameters must be an object schema")
        # Do not let schemas load external documents through the validator.
        if '"$ref"' in json.dumps(schema) or '"$dynamicRef"' in json.dumps(schema):
            raise ValueError("schema references are not supported")
        tree = ast.parse(tool["source"])
        if not any(
            isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body
        ):
            raise ValueError("source must define run(frames, params)")


class Library:
    """Store immutable snapshots; CURRENT can roll back without deleting evidence."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def save(self, tools: list[dict]) -> str:
        validate_tools(tools)
        version = digest(tools)
        path = self.root / f"{version}.json"
        if not path.exists():
            with path.open("x") as file:
                json.dump(tools, file, indent=2)
        self.load(version)
        return version

    def load(self, version: str) -> list[dict]:
        if not re.fullmatch(r"[0-9a-f]{64}", version):
            raise ValueError("invalid version")
        tools = json.loads((self.root / f"{version}.json").read_text())
        if digest(tools) != version:
            raise ValueError("library hash mismatch")
        validate_tools(tools)
        return tools

    def promote(self, version: str) -> None:
        self.load(version)
        temporary = self.root / ".CURRENT.tmp"
        temporary.write_text(version + "\n")
        temporary.replace(self.root / "CURRENT")


class Sandbox:
    """Run NumPy tools with only a read-only sensor bundle and no network/GPU."""

    def __init__(self, image: str):
        # Resolve the tag once: every call in this process uses the same image.
        self.image = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
        ).strip()

    def run(self, tool: dict, params: dict, frames: list[dict]) -> dict:
        import numpy as np

        Draft202012Validator(tool["parameters"]).validate(params)
        with tempfile.TemporaryDirectory(prefix="sensor-tool-") as directory:
            root = Path(directory)
            root.chmod(0o755)
            arrays = {}

            def encode(value: Any) -> Any:
                if isinstance(value, np.ndarray):
                    key = f"array_{len(arrays)}"
                    arrays[key] = value
                    return {"__array__": key}
                if isinstance(value, dict):
                    return {k: encode(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [encode(v) for v in value]
                return value

            (root / "input.json").write_text(
                json.dumps({"frames": encode(frames), "params": params})
            )
            np.savez(root / "arrays.npz", **arrays)
            (root / "candidate.py").write_text(tool["source"])
            (root / "worker.py").write_bytes(
                Path(__file__).with_name("worker.py").read_bytes()
            )
            for path in root.iterdir():
                path.chmod(0o644)
            name = f"sensor-tool-{uuid.uuid4().hex}"
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "65534:65534",
                "--pids-limit",
                "32",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--ulimit",
                "fsize=65536:65536",
                "-e",
                "OPENBLAS_NUM_THREADS=1",
                "-e",
                "OMP_NUM_THREADS=1",
                "--mount",
                f"type=bind,src={root},dst=/input,readonly",
                "--entrypoint",
                "python",
                self.image,
                "-I",
                "-B",
                "/input/worker.py",
            ]
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            output, errors = bytearray(), bytearray()
            deadline = time.monotonic() + 15
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, output)
                    selector.register(process.stderr, selectors.EVENT_READ, errors)
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("sensor tool exceeded 15 seconds")
                        for key, _ in selector.select(min(remaining, 1)):
                            chunk = os.read(key.fileobj.fileno(), 8192)
                            if not chunk:
                                selector.unregister(key.fileobj)
                            else:
                                key.data.extend(chunk)
                                if len(output) + len(errors) > 65536:
                                    raise ValueError(
                                        "sensor tool output exceeded 64 KiB"
                                    )
                if process.wait(timeout=1):
                    raise RuntimeError(
                        "sensor tool failed: " + errors.decode(errors="replace")[-1000:]
                    )
            finally:
                subprocess.run(
                    ["docker", "rm", "-f", name], capture_output=True, timeout=10
                )
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()
            if len(output) > 32768:
                raise ValueError("sensor result exceeds 32 KiB")
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError("sensor result must be an object")
            json.dumps(result, allow_nan=False)
            return result
