# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Perception research registered on RPent's native LIBERO toolkit."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ConfigDict, Field, create_model, model_validator

from robots.libero.research.library import Library, Sandbox, validate_tools
from robots.libero.research.sensors import ACTIONS, EXECUTION_FIELDS, SensorInterface
from robots.libero.toolkit import LiberoToolkit
from rpent.evaluation.result import write_json_atomic
from rpent.tools import Tool, ToolResult

SYSTEM_PROMPT = """Complete the robot task using the provided tools. Start with view_env_state to read the instruction and initial RGB/proprioception. Every motion returns updated agentview and wrist images, in that order, both 256x256; do not read the same frame again. Row zero is at the top. Motion coordinates are world metres. Use pi0_pick to grasp, then move_to and release. Controller parameters use unchanged RPent defaults. Execution counts describe progress, not success.
Segmentation returns a mask overlay, not verified object identity. Inspect it; use point-based segment if text is ambiguous. Generated sensor tools compute evidence from up to four recorded frames and existing masks. Call finish with your assessment when done or stuck. Task recipes, simulator object state and native success are unavailable to you."""

_OMITTED = object()


def _arguments_model(name: str, schema: dict, base=None):
    validator = Draft202012Validator(schema)

    @model_validator(mode="before")
    @classmethod
    def check_schema(cls, value):
        error = next(validator.iter_errors(value), None)
        if error is not None:
            raise ValueError(error.message)
        return value

    options = {"__validators__": {"check_schema": check_schema}}
    if base is not None:
        return create_model(name, __base__=base, **options)
    return create_model(
        name,
        __config__=ConfigDict(extra="forbid"),
        **options,
        **{
            key: (
                Any,
                ...
                if key in schema.get("required", [])
                else Field(default_factory=lambda: _OMITTED),
            )
            for key in schema.get("properties", {})
        },
    )


class SensorResearchToolkit(LiberoToolkit):
    """Keep native execution, scheduling and events; restrict model observations."""

    planner_tools_only = True

    @property
    def planner_stop_result(self):
        if self._runtime_error or self.solved() or self.primitives.env.truncated:
            return {
                "_finish": True,
                "environment_stopped": True,
                "status": "failed" if self._runtime_error else "stopped",
                "summary": self._runtime_error or "Environment episode ended.",
            }
        return None

    def _execute_primitive(self, name, handler, **kwargs):
        # Queued actions also check after acquiring RPent's exclusive scheduler.
        if self.planner_stop_result is not None:
            return ToolResult(data={"error": "Environment episode ended."})
        return super()._execute_primitive(name, handler, **kwargs)

    def __init__(self, *, sensor_library: str, sandbox_image: str, **kwargs):
        tools = json.loads(Path(sensor_library).read_text())
        validate_tools(tools)
        self._research_trace = []
        self._runtime_error = None
        self._sensor_lock = threading.Lock()
        self._trace_lock = threading.Lock()
        sandbox = Sandbox(sandbox_image) if tools else None
        super().__init__(**kwargs)
        self._library_version = Library(self._state_output_dir / "sensor-library").save(
            tools
        )
        self.sensors = SensorInterface(self, tools, sandbox)
        originals = self._tools
        self._tools = {}
        for definition in self.sensors.declarations:
            name, schema = definition["name"], definition["parameters"]
            if name in ACTIONS:
                original = originals[name]
                self.add_tool(
                    replace(
                        original,
                        description=definition["description"],
                        _input_schema=schema,
                        args_schema=_arguments_model(
                            name, schema, original.args_schema
                        ),
                    )
                )
            elif name == "finish":
                self.add_tool(
                    replace(
                        originals[name],
                        description="End this attempt with status and summary. Your assessment does not determine the evaluator's result.",
                    )
                )
            else:
                description = definition["description"]
                # llama.cpp's tool grammar loses root properties when oneOf
                # contains only required clauses. Keep XOR validation on the
                # executor while exposing the simple property schema.
                model_schema = (
                    {k: v for k, v in schema.items() if k != "oneOf"}
                    if name == "segment"
                    else schema
                )
                if name == "view_env_state":
                    description = "Read the task instruction and RGB/proprioception. Call once initially; motions return updated observations. Step -1 is latest."
                self.add_tool(
                    Tool(
                        name=name,
                        description=description,
                        args_schema=_arguments_model(name, schema),
                        handler=partial(self._sensor_call, name),
                        _input_schema=model_schema,
                        readonly=True,
                    )
                )
        self._save_trace()

    def _sensor_call(self, name: str, **kwargs) -> ToolResult:
        with self._sensor_lock:
            return self.sensors.execute(
                name, {k: v for k, v in kwargs.items() if v is not _OMITTED}
            )

    def get_env_state(
        self, *, command: dict, result: dict, elapsed_s: float
    ) -> ToolResult:
        super().get_env_state(command=command, result=result, elapsed_s=elapsed_s)
        observed = self.sensors.observe()
        observed.data["execution"] = {
            k: result[k] for k in EXECUTION_FIELDS if k in result
        }
        execution = observed.data["execution"]
        if "chunks_used" in execution and "max_chunks" in execution:
            execution["chunk_budget_used"] = (
                execution["chunks_used"] >= execution["max_chunks"]
            )
        return observed

    def execute_tool(self, name: str, input_dict: dict) -> ToolResult:
        result = super().execute_tool(name, input_dict)
        if result.data.get("state_capture_error"):
            self._runtime_error = (
                "Environment observation capture failed; inspect native logs."
            )
        if name in ACTIONS and result.is_error:
            # The native executor attaches diagnostics on failure; retain only
            # sensor evidence and execution counters at the model boundary.
            result.data = {
                k: v
                for k, v in result.data.items()
                if k in {"step", "proprio", "image_order", "image_size", "execution"}
            }
            result.data["error"] = "action execution failed; inspect current sensors"
        if name == "view_env_state" and not result.is_error:
            result.data["instruction"] = self.state.get(
                input_dict.get("step", -1)
            ).extras.get("task_language")
        with self._trace_lock:
            self._research_trace.append(
                {
                    "turn": len(self._research_trace),
                    "decision": {"tool": name, "arguments": input_dict},
                    "result": result.data,
                }
            )
            self._save_trace()
        return result

    def _save_trace(self) -> None:
        write_json_atomic(
            self._state_output_dir / "sensor-trace.json",
            {
                "library": self._library_version,
                "trajectory": self._research_trace,
                "native_success": self.solved(),
                "truncated": bool(self.primitives.env.truncated),
                "error": self._runtime_error,
            },
        )

    def write_recipe(self, recipe_tag: str) -> str:
        """Research episodes do not publish task recipes."""
        return ""


def finalize_run(context):
    """Write evaluator results only for explicitly enabled research runs."""
    trace = context.output_dir / "sensor-trace.json"
    if not trace.exists():
        return None
    report = json.loads(trace.read_text())
    report.update(
        native_success=context.environment_success,
        error=context.agent_error or report.get("error"),
        seconds=context.elapsed_s,
        stats=dict(context.stats),
        model=context.model,
        planner=context.planner,
    )
    return write_json_atomic(context.output_dir / "research-report.json", report)
