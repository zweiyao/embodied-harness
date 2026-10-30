# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Per-run Flexiv allowlists and isolated programs on recorded observations."""

import copy
import json
import time
import uuid
from functools import partial

from jsonschema import Draft202012Validator

from robots.flexiv.catalog import catalog, generated_availability
from robots.flexiv.sensors import alignment_frames
from robots.flexiv.toolkit import FlexivToolkit, tool_methods
from robots.libero.research.library import Sandbox, digest, validate_tools
from robots.libero.research.native import _OMITTED, _arguments_model
from rpent.dashboard.workbench import RunJournal, write_json
from rpent.tools import Tool, ToolResult, iter_tools
from rpent.tools.common import CommonTools


def validate_selection(selected: list[dict], control_mode: str, meta: dict) -> None:
    """Reject stale, incompatible or unavailable selections before observation."""
    native = {item["name"]: item for item in catalog(control_mode=control_mode)}
    available = {
        getattr(FlexivToolkit, method).name
        for method in tool_methods(meta, control_mode)
    } | {tool.name for tool in iter_tools(CommonTools)}
    names = [item["name"] for item in selected]
    if "finish" not in names or len(names) != len(set(names)):
        raise ValueError("Select finish and at most one version per tool")
    for item in selected:
        missing = set(item.get("dependencies", [])) - set(names)
        if missing:
            raise ValueError(f"Missing tool dependencies: {sorted(missing)}")
        if item["origin"] == "native":
            current = native.get(item["name"])
            if current is None or any(
                item.get(key) != current[key]
                for key in ("version", "source", "parameters", "description")
            ):
                raise ValueError(f"Native tool changed since selection: {item['name']}")
            if item["name"] not in available:
                raise ValueError(
                    f"Selected tool {item['name']} is unavailable under the current "
                    "Flexiv enable/calibration state; enable its capability or deselect it"
                )
        elif item["origin"] == "generated":
            definition = {
                k: item[k] for k in ("name", "description", "parameters", "source")
            }
            validate_tools([definition])
            if item["version"] != digest([definition]):
                raise ValueError(
                    f"Generated tool version does not match source: {item['name']}"
                )
            supported, reason = generated_availability(item)
            if not supported:
                raise ValueError(reason)
            if "localize_target" not in names:
                raise ValueError("Missing tool dependencies: ['localize_target']")
        else:
            raise ValueError("Tool origin must be native or generated")
    if (
        meta.get("reset_before_task")
        and meta.get("motion_enabled")
        and "reset_home" not in names
    ):
        raise ValueError(
            "This environment requires startup reset_home; select it or disable automatic startup reset"
        )


class ManualToolkit(FlexivToolkit):
    """Preserve native control/feedback while exposing only frozen selected tools."""

    planner_tools_only = True

    def __init__(
        self, *, selected, journal=None, sandbox_image="embodied-sensor:pilot", **kwargs
    ):
        self.selection = copy.deepcopy(selected)
        validate_selection(
            self.selection, kwargs.get("control_mode", "native"), kwargs["env"].meta
        )
        self.journal = journal or RunJournal(kwargs["output_dir"])
        self.sandbox = (
            Sandbox(sandbox_image)
            if any(item["origin"] == "generated" for item in self.selection)
            else None
        )
        super().__init__(**kwargs)
        available, self._tools = self._tools, {}
        for item in self.selection:
            if item["origin"] == "native":
                self.add_tool(available[item["name"]])
            else:
                definition = {
                    k: item[k] for k in ("name", "description", "parameters", "source")
                }
                self.add_tool(
                    Tool(
                        name=item["name"],
                        description=item["description"],
                        args_schema=_arguments_model(item["name"], item["parameters"]),
                        _input_schema=item["parameters"],
                        handler=partial(self._generated, definition),
                        readonly=True,
                    )
                )

    def _generated(self, definition, **params):
        params = {k: v for k, v in params.items() if v is not _OMITTED}
        Draft202012Validator(definition["parameters"]).validate(params)
        with self._observation_lock:
            frames = alignment_frames(
                [record.to_blob() for record in self.state.records()],
                lambda name, step: self.state.load(name, step=step),
                params,
            )
        self.journal.append(
            "generated_input",
            {
                "name": definition["name"],
                "steps": [frame["step"] for frame in frames],
                "params": params,
                "sandbox_image": self.sandbox.image,
            },
        )
        return ToolResult(data=self.sandbox.run(definition, params, frames))

    def execute_tool(self, name, input_dict):
        call_id, started = uuid.uuid4().hex, time.monotonic()
        self.journal.append(
            "tool_request", {"call_id": call_id, "name": name, "arguments": input_dict}
        )
        try:
            result = super().execute_tool(name, input_dict)
        except Exception as exc:
            self.journal.append(
                "tool_error", {"call_id": call_id, "name": name, "error": str(exc)}
            )
            raise
        self.journal.append(
            "tool_response",
            {
                "call_id": call_id,
                "name": name,
                "result": result.data,
                "images": result.images,
                "elapsed_s": time.monotonic() - started,
            },
        )
        generated = [
            item["version"]
            for item in self.selection
            if item["name"] == name and item["origin"] == "generated"
        ]
        if generated:
            with self.journal.lock:
                path = self.journal.root / "tool-invocations.json"
                versions = json.loads(path.read_text()) if path.exists() else []
                write_json(path, sorted(set(versions + generated)))
        return result
