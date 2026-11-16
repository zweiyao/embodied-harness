# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""LIBERO prompt bundle assembly."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from robots.libero.prompts import explore as explore_parts
from robots.libero.prompts.evaluate import allowed_primitives
from rpent.prompt.composition import (
    COMMON_DIR,
    memory_available,
    system_sections,
    task_file,
    user_sections,
)
from rpent.prompt.utils import PromptNode

ROOT = Path(__file__).parent / "prompts"


def system_prompt(
    variables: Mapping[str, object] | None = None,
) -> PromptNode:
    """Assemble the LIBERO system prompt for the selected run mode."""
    if (variables or {}).get("language_materials"):
        from robots.libero.research.language_materials import material_prompt

        return material_prompt(variables, "system.md")
    values = variables or {}
    eef = any(t.get("name") == "move_eef" for t in values.get("manual_tools", []))
    result = system_sections(
        COMMON_DIR,
        ROOT / ("control_eef.md" if eef else "control_native.md"),
        analysis=values.get("analysis_enabled", False),
        variables=values,
    )
    if values.get("mode", "eval") == "explore":
        old = explore_parts.system_prompt(variables)
        result["EXPLORATION RULES"] = old["RULES (NON-NEGOTIABLE)"]
        result["RESTORATION"] = (
            "Also allowed: `reset` within the explicit exploration-mode rules."
        )
    else:
        result["EPISODE"] = "SINGLE-ATTEMPT MODE: one episode; do not reset."
    if "manual_tools" not in values:
        result["NATIVE ACTIONS"] = allowed_primitives(
            bool(values.get("enable_direct_action", False))
        )
    return result


def user_prompt(variables: Mapping[str, object] | None = None) -> PromptNode:
    """Assemble the LIBERO user prompt tree."""
    if (variables or {}).get("language_materials"):
        from robots.libero.research.language_materials import material_prompt

        return material_prompt(variables, "user.md")
    values = variables or {}
    key = f"{values.get('suite', 'suite')}_t{values.get('task', 0)}"
    return user_sections(
        COMMON_DIR,
        task_file(ROOT / "tasks", key),
        memory_available=memory_available(values),
        variables=values,
    )


__all__ = ["system_prompt", "user_prompt"]
