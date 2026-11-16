# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""UniVTAC robot contracts and task guidance through the shared composer."""

from pathlib import Path

from rpent.prompt.composition import (
    COMMON_DIR,
    memory_available,
    system_sections,
    task_file,
    user_sections,
)

ROOT = Path(__file__).parent / "prompts"


def system_prompt(variables=None):
    values = variables or {}
    selected = values.get("manual_tools", [])
    control = (
        "control_eef.md"
        if any(t["name"] == "move_eef" for t in selected)
        else "control_native.md"
    )
    result = system_sections(
        COMMON_DIR,
        ROOT / control,
        analysis=values.get("analysis_enabled", False),
        variables=values,
    )
    if not values.get("analysis_enabled", False):
        result["AVAILABLE TOOLS"] = (
            "Use only the registered tools listed below. Do not bypass the selection "
            "with shell, files, network or another controller. Inspect returned evidence."
        )
    result["TOOL SUMMARY"] = "\n".join(
        f"- {t['name']}: {t['description'].strip().splitlines()[0]}" for t in selected
    )
    if any(t.get("origin") == "generated" for t in selected):
        result["GENERATED EVIDENCE"] = (
            "Generated perception tools provide measurements and evidence, not an official success verdict. Check their applicability."
        )
    return result


def user_prompt(variables=None):
    values = variables or {}
    return user_sections(
        COMMON_DIR,
        task_file(ROOT / "tasks", "default"),
        memory_available=memory_available(values),
        variables=values,
    )
