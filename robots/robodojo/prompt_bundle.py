# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""RoboDojo-owned control and task selection for shared prompt composition."""

from pathlib import Path

from rpent.prompt.composition import (
    COMMON_DIR,
    memory_available,
    system_sections,
    task_file,
    user_sections,
)

ROOT = Path(__file__).parent / "prompts"


def _eef(variables):
    return any(t.get("name") == "move_eef" for t in variables.get("manual_tools", []))


def system_prompt(variables=None):
    values = variables or {}
    if values.get("mode") == "eval-fair":
        return {
            "EXECUTION": "Replay the frozen plan using live RGB-D and robot proprioception. No language model participates."
        }
    control = "control_eef.md" if _eef(values) else "control_native.md"
    return system_sections(
        COMMON_DIR,
        ROOT / control,
        analysis=values.get("analysis_enabled", False),
        variables=values,
        recovery=ROOT / "execution_recovery.md",
    )


def user_prompt(variables=None):
    values = variables or {}
    if values.get("mode") == "eval-fair":
        return {"TASK": "{{task}} / layout {{layout}}"}
    key = str(values.get("task", "default"))
    if key == "arrange_largest_number_random":
        key = "arrange_largest_number"
    result = user_sections(
        COMMON_DIR,
        task_file(ROOT / "tasks", key),
        memory_available=memory_available(values),
        variables=values,
    )
    result.variables["control_mode"] = "eef_absolute" if _eef(values) else "native"
    return result
