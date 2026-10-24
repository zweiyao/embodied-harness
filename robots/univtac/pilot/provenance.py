# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Concrete code, controller and sandbox evidence for the bounded pilot."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from robots.univtac.control import (
    ACTION_REPEAT,
    CHUNK_LIMIT,
    COMMAND_LIMIT,
    MAX_JOINT_INCREMENT,
)
from rpent.utils.config import get_repo_root

SOURCES = (
    "robots/univtac/control.py",
    "robots/univtac/backend.py",
    "robots/univtac/env_client.py",
    "robots/univtac/env_server.py",
    "robots/univtac/observations.py",
    "robots/univtac/toolkit.py",
    "robots/univtac/perception.py",
    "robots/univtac/prompt_bundle.py",
    "robots/univtac/robot_spec.py",
    "robots/univtac/_panda/__init__.py",
    "robots/univtac/_panda/ik.py",
    "robots/univtac/_panda/state.py",
    "robots/univtac/_panda/transforms.py",
    "robots/univtac/pilot/__init__.py",
    "robots/univtac/pilot/execution.py",
    "robots/univtac/pilot/provenance.py",
    "rpent/planner/base.py",
    "rpent/planner/api_loop.py",
    "rpent/planner/codex.py",
    "rpent/planner/request_timeout.py",
    "rpent/planner/utils/http_mcp_server.py",
    "rpent/tools/base.py",
    "rpent/tools/toolkit.py",
    "rpent/tools/common.py",
    "rpent/session/base.py",
    "robots/libero/research/native.py",
    "robots/libero/research/library.py",
    "robots/libero/research/worker.py",
)


def collect(
    root: str | Path | None = None, *, sandbox_image: str = "embodied-sensor:pilot"
) -> dict:
    """Hash the actual checkout and resolve the image before simulator startup.

    All conditions retain the same sandbox image identity even when their tool
    selection does not invoke it. Only the resolved ID may be passed to Sandbox.
    """
    root = Path(root or get_repo_root()).resolve()
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", sandbox_image],
        text=True,
        timeout=30,
    ).strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("Docker did not return an immutable sandbox image ID")
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=30
    ).strip()
    return {
        "controller": {
            "action_repeat": ACTION_REPEAT,
            "command_limit": COMMAND_LIMIT,
            "chunk_limit": CHUNK_LIMIT,
            "max_joint_increment_rad": MAX_JOINT_INCREMENT,
            "sandbox_image": image,
        },
        "code_revision": {
            "git_head": revision,
            "sources": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in SOURCES
            },
        },
        "memory": {"mode": "empty_read_only", "shared": False, "file_tools": False},
    }
