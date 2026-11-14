# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Native workbench declarations and recording shared by simulator adapters."""

from __future__ import annotations

import hashlib
import inspect
import time
import uuid
from typing import TYPE_CHECKING

from rpent.tools import Tool, ToolResult

if TYPE_CHECKING:
    from rpent.dashboard.workbench import RunJournal


def build_catalog(declarations: list[Tool], auxiliary: set[str]) -> list[dict]:
    """Describe native declarations; later owners replace same-name tools."""
    current = {t.name: t for t in declarations}
    result = []
    for entry in current.values():
        source = inspect.getsource(entry.handler)
        result.append(
            {
                "id": f"native:{entry.name}",
                "name": entry.name,
                "origin": "native",
                "category": "auxiliary"
                if entry.name in auxiliary
                else "perception"
                if entry.readonly
                else "control",
                "description": entry.description,
                "parameters": entry.input_schema,
                "version": hashlib.sha256(source.encode()).hexdigest(),
                "source": source,
                "required": entry.name == "finish",
                "dependencies": [],
                "validation": "native",
                "input_contract": entry.description,
                "example": None,
            }
        )
    return result


def validate_native_selection(selected: list[dict], catalog: list[dict]) -> None:
    """Require finish and a frozen selection of current native declarations."""
    current = {t["id"]: t for t in catalog}
    names = [t["name"] for t in selected]
    if "finish" not in names or len(names) != len(set(names)):
        raise ValueError("Select finish and at most one version per tool")
    for item in selected:
        original = current.get(item["id"])
        if item.get("origin") != "native" or original is None:
            raise ValueError("This workbench supports native tools only")
        if any(
            item.get(key) != original[key]
            for key in ("name", "description", "parameters", "source", "version")
        ):
            raise ValueError(f"Native tool changed since selection: {item['name']}")


class NativeToolSelectionMixin:
    """Keep native handlers and control guards while selecting exposed tools."""

    def configure_workbench_tools(
        self, selected: list[dict] | None, journal: RunJournal | None
    ) -> None:
        """Expose the frozen allowlist without replacing native control guards."""
        if selected is None:
            return
        names = {t["name"] for t in selected}
        missing = names - set(self._tools)
        if missing:
            raise ValueError(
                f"Selected native tools are not registered: {sorted(missing)}"
            )
        self._tools = {
            name: entry for name, entry in self._tools.items() if name in names
        }
        self.planner_tools_only = True
        if journal is not None:
            self.journal = journal

    def execute_tool(self, name: str, input_dict: dict) -> ToolResult:
        journal = getattr(self, "journal", None)
        if journal is None:
            return super().execute_tool(name, input_dict)
        call_id, started = uuid.uuid4().hex, time.monotonic()
        journal.append(
            "tool_request", {"call_id": call_id, "name": name, "arguments": input_dict}
        )
        try:
            result = super().execute_tool(name, input_dict)
        except Exception as exc:
            journal.append(
                "tool_error", {"call_id": call_id, "name": name, "error": str(exc)}
            )
            raise
        journal.append(
            "tool_response",
            {
                "call_id": call_id,
                "name": name,
                "result": result.data,
                "images": result.images,
                "elapsed_s": time.monotonic() - started,
            },
        )
        return result
