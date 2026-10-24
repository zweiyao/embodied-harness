# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Model-facing LIBERO boundary: sensors, fixed actions and frozen tool versions."""

from __future__ import annotations

import copy
import io

import imageio.v2 as imageio
import numpy as np

from rpent.tools import ToolResult

ACTIONS = {
    "pi0_pick",
    "pi0_doubled",
    "move_to",
    "rotate_wrist",
    "rotate_pitch",
    "move_pose",
    "release",
    "set_gripper",
}
PROPRIO = ("robot0_eef_pos", "robot0_eef_quat", "robot0_gripper_qpos")
CALIBRATION = ("intrinsic_K", "extrinsic_cam2world", "height", "width", "camera_name")


def declaration(
    name: str, description: str, properties: dict, required: list[str] | None = None
) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


EXECUTION_FIELDS = ("chunks_used", "max_chunks", "steps_used", "max_steps", "steps")


class SensorInterface:
    """Wrap a LiberoToolkit without changing its controller or privileged trace."""

    def __init__(self, toolkit, tools: list[dict], sandbox):
        self.toolkit = toolkit
        self.state = toolkit.state
        self.tools = {t["name"]: copy.deepcopy(t) for t in tools}
        self.sandbox = sandbox
        self.masks: dict[int, dict] = {}
        self.declarations = self._declarations()

    def _declarations(self) -> list[dict]:
        output = []
        for tool in self.toolkit.list_tools():
            if tool.name not in ACTIONS:
                continue
            schema = copy.deepcopy(tool.input_schema)
            description = tool.description
            if tool.name in {"pi0_pick", "pi0_doubled"}:
                for name, prop in schema["properties"].items():
                    if name != "prompt":
                        prop["const"] = tool.args_schema.model_fields[name].default
                description += (
                    "\nFor this experiment optional controller parameters are fixed "
                    "to the unchanged RPent defaults shown in the schema."
                )
            output.append(
                {"name": tool.name, "description": description, "parameters": schema}
            )
        step = {"type": "integer", "minimum": -1, "default": -1}
        camera = {
            "type": "string",
            "enum": ["agentview", "wrist"],
            "default": "agentview",
        }
        output += [
            declaration(
                "view_env_state",
                "Read a recorded observation. Latest RGB and proprioception are already supplied every turn; use this for an older step rather than refreshing an unchanged frame. Images are 256x256, aligned with depth. Step -1 is latest.",
                {"step": step},
            ),
            declaration(
                "view_camera_meta",
                "Read sensor calibration for a recorded step.",
                {"step": step, "camera": camera},
            ),
            declaration(
                "back_project",
                "Project one 256x256 image pixel to world XYZ in metres. Row is y, col is x.",
                {
                    "step": step,
                    "camera": camera,
                    "row": {"type": "integer", "minimum": 0, "maximum": 255},
                    "col": {"type": "integer", "minimum": 0, "maximum": 255},
                },
                ["row", "col"],
            ),
            declaration(
                "segment",
                "RPent SAM3 segmentation using exactly one text prompt or positive point [row, col]. Returns mask_id, score, box and a mask overlay. Inspect the overlay to identify the selected region; different prompts do not establish distinct object identities. If text is ambiguous, select a point on the visible target. Masks are available to generated tools at the same recorded step.",
                {
                    "step": step,
                    "camera": camera,
                    "prompt": {"type": "string", "minLength": 1},
                    "point": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 255},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "min_score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "default": 0.2,
                    },
                },
            ),
            declaration(
                "finish",
                "End this attempt when complete or unable to proceed; your claim is not the evaluator's score.",
                {"summary": {"type": "string"}},
                ["summary"],
            ),
        ]
        for item in output:
            if item["name"] == "segment":
                item["parameters"]["oneOf"] = [
                    {"required": ["prompt"]},
                    {"required": ["point"]},
                ]
        output += [
            {k: t[k] for k in ("name", "description", "parameters")}
            for t in self.tools.values()
        ]
        return output

    def observe(self, step: int = -1) -> ToolResult:
        record = self.state.get(step)
        return ToolResult(
            data={
                "step": record.step_idx,
                "proprio": {k: record.state[k] for k in PROPRIO},
                "image_order": ["agentview", "wrist"],
                "image_size": [256, 256],
            },
            images=[
                self.state.load_bytes(f"{c}.png", step=record.step_idx)
                for c in ("agentview", "wrist")
            ],
        )

    def frames(self) -> list[dict]:
        frames = []
        for record in self.state.records()[-4:]:
            cameras = {}
            for camera in ("agentview", "wrist"):
                meta = self.state.load(f"{camera}_metadata.json", step=record.step_idx)
                cameras[camera] = {
                    "rgb": self.state.load(f"{camera}.png", step=record.step_idx),
                    "depth": self.state.load(
                        f"{camera}_depth.npz", step=record.step_idx
                    ),
                    "world": self.state.load(
                        f"{camera}_world.npz", step=record.step_idx
                    ),
                    "calibration": {k: meta[k] for k in CALIBRATION if k in meta},
                }
            frames.append(
                {
                    "step": record.step_idx,
                    "proprio": {k: record.state[k] for k in PROPRIO},
                    "cameras": cameras,
                    "masks": self.masks.get(record.step_idx, {}),
                }
            )
        return frames

    def execute(self, name: str, arguments: dict) -> ToolResult:
        from jsonschema import Draft202012Validator

        declarations = {t["name"]: t for t in self.declarations}
        try:
            if name not in declarations:
                raise ValueError("unknown tool")
            Draft202012Validator(declarations[name]["parameters"]).validate(arguments)
            if name in ACTIONS:
                previous_step = self.state.get().step_idx
                result = self.toolkit.execute_tool(name, arguments)
                record = self.state.get()
                # RPent returns images but stores the primitive result in StepRecord.
                execution_result = (
                    record.result or {} if record.step_idx > previous_step else {}
                )
                observed = self.observe()
                observed.data["execution"] = {
                    k: execution_result[k]
                    for k in EXECUTION_FIELDS
                    if k in execution_result
                }
                execution = observed.data["execution"]
                if "chunks_used" in execution and "max_chunks" in execution:
                    execution["chunk_budget_used"] = (
                        execution["chunks_used"] >= execution["max_chunks"]
                    )
                if result.is_error or execution_result.get("error"):
                    observed.data["error"] = (
                        "action execution failed; inspect current sensors"
                    )
                return observed
            if name == "finish":
                return ToolResult(data={"finished": True})
            if name in self.tools:
                return ToolResult(
                    data=self.sandbox.run(self.tools[name], arguments, self.frames())
                )
            if name == "view_env_state":
                return self.observe(**arguments)
            record = self.state.get(arguments.get("step", -1))
            camera = arguments.get("camera", "agentview")
            if name == "view_camera_meta":
                meta = self.state.load(f"{camera}_metadata.json", step=record.step_idx)
                return ToolResult(data={k: meta[k] for k in CALIBRATION if k in meta})
            if name == "back_project":
                world = self.state.load(f"{camera}_world.npz", step=record.step_idx)
                xyz = world[arguments["row"], arguments["col"]]
                return ToolResult(
                    data={"world_xyz": xyz.tolist() if np.isfinite(xyz).all() else None}
                )
            result = self.toolkit.primitives._sam3_client.segment(
                self.state.load_bytes(f"{camera}.png", step=record.step_idx),
                text_prompt=arguments.get("prompt"),
                point=arguments.get("point"),
                min_score=arguments.get("min_score", 0.2),
            )
            if not result.found:
                return ToolResult(data={"mask_id": None, "score": result.score})
            masks = self.masks.setdefault(record.step_idx, {})
            mask_id = f"m{len(masks)}"
            masks[mask_id] = {
                "camera": camera,
                "mask": np.asarray(result.mask, dtype=bool),
                "score": float(result.score),
            }
            from robots.libero.tools import _make_segment_overlay

            overlay = _make_segment_overlay(
                self.state.load(f"{camera}.png", step=record.step_idx), result.mask
            )
            images = []
            if overlay is not None:
                buffer = io.BytesIO()
                imageio.imwrite(buffer, overlay, format="png")
                images.append(buffer.getvalue())
            return ToolResult(
                data={
                    "step": record.step_idx,
                    "camera": camera,
                    "mask_id": mask_id,
                    "score": float(result.score),
                    "box": result.box,
                    "prompt": arguments.get("prompt"),
                    "point": arguments.get("point"),
                },
                images=images,
            )
        except Exception as exc:
            if name in self.tools:
                return ToolResult(
                    data={
                        "error": f"sensor computation failed: {type(exc).__name__}: {str(exc)[:1200]}"
                    }
                )
            # Exception messages from adapters can contain privileged state/paths.
            return ToolResult(
                data={
                    "error": f"{name} failed ({type(exc).__name__}); check arguments or sensor availability"
                }
            )
