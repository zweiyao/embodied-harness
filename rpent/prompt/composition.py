# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""File-backed prompt sections and their exact source provenance."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

COMMON_DIR = Path(__file__).parent


class ComposedPrompt(dict):
    """An ordinary PromptNode mapping with the files read to construct it."""

    def __init__(self, sections, sources=(), *, variables=None):
        super().__init__(sections)
        self.sources = tuple(sources)
        self.variables = dict(variables or {})


def read_sections(files: Mapping[str, Path]) -> ComposedPrompt:
    """Read only explicit section files, recording the bytes actually consumed."""
    sections, sources = {}, []
    for name, path in files.items():
        raw = path.read_bytes()
        sections[name] = raw.decode("utf-8")
        sources.append(
            {
                "section": name,
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return ComposedPrompt(sections, sources)


def task_file(directory: Path, task_key: str) -> Path:
    """Select one validated task supplement or the robot's explicit default."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", task_key):
        raise ValueError("Task file key must be a validated task identifier")
    directory = directory.resolve()
    selected = directory / f"{task_key}.md"
    if not selected.resolve().is_relative_to(directory):
        raise ValueError("Task supplement outside robot task directory")
    result = selected if selected.is_file() else directory / "default.md"
    if not result.resolve().is_relative_to(directory):
        raise ValueError("Default supplement outside robot task directory")
    return result


def availability_prompt(selected, *, analysis=False):
    """Describe actual tools, distinguishing robot control from local analysis."""
    names = ", ".join(t["name"] for t in selected)
    if analysis:
        return (
            f"Registered RPent tools: {names}.\n"
            "Use only these registered interfaces for robot control and live perception. "
            "Available Codex analysis tools may inspect recorded evidence, run calculations, "
            "crop images and maintain notes within the permitted workspace. They do not "
            "authorize another controller connection, policy inference, reset, scene-truth "
            "query, network administration or bypass of the selected robot tools. "
            "Tool schemas and current feedback define the actual arguments and limits.\n\n"
        )
    eef_guidance = (
        "Use the latest images and EEF pose to choose the next short move_eef target. "
        "Revise it using returned images, measured pose and object motion; EEF arrival is not task completion.\n\n"
        if any(t["name"] == "move_eef" for t in selected)
        else ""
    )
    return (
        "EXPERIMENT TOOL SELECTION (overrides references to unavailable tools in the following guides): "
        f"Only these tools are enabled: {names}. Do not call any other tool or use shell/files/network to bypass this selection. "
        "Skip guide steps that require disabled tools. Native observations and action feedback remain unchanged. "
        "Generated perception tools compute evidence, not task success.\n\n"
        + eef_guidance
    )


def system_sections(
    common_dir: Path,
    control: Path,
    *,
    analysis=False,
    variables: Mapping[str, Any] | None = None,
) -> ComposedPrompt:
    """Compose fixed requirements, the robot contract and actual tool access."""
    values = variables or {}
    files = {"GENERAL REQUIREMENTS": common_dir / "common.md", "ROBOT CONTROL": control}
    if analysis:
        files["ANALYSIS WORKSPACE"] = common_dir / "analysis_workspace.md"
    result = read_sections(files)
    if "manual_tools" in values:
        result["AVAILABLE TOOLS"] = availability_prompt(
            values["manual_tools"], analysis=analysis
        )
    return result


def user_sections(
    common_dir: Path,
    task: Path,
    *,
    memory_available: bool,
    variables: Mapping[str, Any] | None = None,
) -> ComposedPrompt:
    """Compose the current task, known runtime limits and optional index pointer."""
    values = variables or {}
    files = {"TASK": task}
    if {"max_turns", "planner_timeout_s", "output_dir"} <= values.keys():
        files["RUN CONTEXT"] = common_dir / "runtime.md"
    if memory_available:
        files["EXPERIENCE LIBRARY"] = common_dir / "memory.md"
    return read_sections(files)


def memory_available(variables: Mapping[str, Any]) -> bool:
    """Offer a corpus only when its index and a supported reader are present."""
    root = variables.get("memory_dir")
    if not root or not (Path(root) / "MEMORY.md").is_file():
        return False
    selected = variables.get("manual_tools")
    return bool(
        variables.get("analysis_enabled")
        or selected is None
        or any(t["name"] == "read_text_file" for t in selected)
    )
