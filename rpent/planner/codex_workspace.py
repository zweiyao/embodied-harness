# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Run-owned analysis files and Codex filesystem permission configuration."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def prepare_workspace(output_dir: Path, memory_dir: Path | None) -> Path:
    """Create writable notes/scratch separately from host-owned run evidence."""
    root = output_dir.resolve()
    workspace = root / "agent"
    if workspace.is_symlink():
        raise ValueError("Analysis workspace cannot be a symlink")
    workspace.mkdir(parents=True, exist_ok=True)
    if (workspace / "scratch").is_symlink() or (workspace / "NOTES.md").is_symlink():
        raise ValueError("Analysis notes and scratch cannot be symlinks")
    (workspace / "scratch").mkdir(exist_ok=True)
    metadata = workspace / "workspace.json"
    if metadata.is_symlink():
        raise ValueError("workspace.json cannot be a symlink")
    metadata.write_text(
        json.dumps(
            {
                "python_executable": sys.executable,
                "evidence_root": str(root),
                "memory_root": str(memory_dir.resolve()) if memory_dir else None,
                "notes_path": str(workspace / "NOTES.md"),
                "scratch": str(workspace / "scratch"),
                "robot_control": "registered RPent tools only",
            },
            indent=2,
        )
        + "\n"
    )
    notes = workspace / "NOTES.md"
    if not notes.exists():
        notes.write_text(
            "# Episode notes\n\nRecord confirmed progress, geometry estimates, tracking errors and uncertainty.\n"
        )
    return workspace


def analysis_overrides(
    workspace: Path,
    memory_dir: Path | None,
    source_root: Path,
    *,
    full_access: bool = False,
) -> tuple[str, ...]:
    """Select explicit full access or the default restricted analysis profile."""
    features = (
        "features.shell_tool=true",
        "features.unified_exec=true",
        "features.view_image=true",
        "features.view_image_tool=true",
    )
    if full_access:
        return (
            'sandbox_mode="danger-full-access"',
            'approval_policy="never"',
            *features,
        )
    entries = {
        str(source_root.resolve()): "read",
        str(workspace.parent): "read",
        str(workspace): "write",
    }
    if memory_dir is not None:
        entries[str(memory_dir.resolve())] = "read"
    table = (
        "{ "
        + ", ".join(f"{json.dumps(k)} = {json.dumps(v)}" for k, v in entries.items())
        + " }"
    )
    return (
        'default_permissions="rpent_analysis"',
        'permissions.rpent_analysis.extends=":workspace"',
        "permissions.rpent_analysis.filesystem=" + table,
        *features,
    )
