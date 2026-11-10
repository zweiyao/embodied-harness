# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Selectable tools on unchanged native LIBERO observations and controllers."""

import threading
import time
import uuid
from dataclasses import replace
from functools import partial

import numpy as np

from robots.libero.research.library import Sandbox
from robots.libero.research.native import _OMITTED, _arguments_model
from robots.libero.research.sensors import SensorInterface
from robots.libero.toolkit import LiberoToolkit
from rpent.tools import Tool, ToolResult, tool

PLANNER_VIEW_MODE = "calibrated-pair-v1"
PLANNER_VIEW_ARTIFACTS = ("agentview_high.png", "wrist_high.png")


def planner_view_description(name):
    if name == "read_image":
        return (
            "Read the exact saved image by artifact name and step. image_views "
            "identifies its frame; policy and unclassified images are not "
            "calibrated sampling inputs."
        )
    from robots.libero.tools import view_env_state

    return view_env_state.description.replace(
        "Embeds policy, agentview, and wrist images when available.",
        "Embeds calibrated agentview high and wrist high images. "
        "image_views identifies each attached image in order. "
        "Missing required images are reported as an error.",
    )


class RecordingSam3:
    def __init__(self, client):
        self.client = client
        self.local = threading.local()

    def segment(self, *args, **kwargs):
        result = self.client.segment(*args, **kwargs)
        self.local.result = result
        return result


class ManualToolkit(LiberoToolkit):
    planner_tools_only = True

    def __init__(
        self,
        *,
        selected,
        journal,
        sandbox_image="embodied-sensor:pilot",
        planner_view_mode="native",
        **kwargs,
    ):
        if planner_view_mode not in ("native", PLANNER_VIEW_MODE):
            raise ValueError("Unsupported LIBERO planner_view_mode")
        self.planner_view_mode = planner_view_mode
        placement_names = {t["name"] for t in selected} & {
            "preview_placement",
            "align_placement",
        }
        if placement_names and placement_names != {
            "preview_placement",
            "align_placement",
        }:
            raise ValueError("Select preview_placement and align_placement together")
        self.journal = journal
        self._ended = False
        self.mask_lock = threading.RLock()
        super().__init__(**kwargs)
        self.sensors = SensorInterface(self, [], None)
        self.add_tool(self.read_image)
        optional_moves = {t["name"] for t in selected} & {"move_eef", "translate_to"}
        if optional_moves:
            from robots.libero.eef_control import EefControl

            if "move_eef" in optional_moves:
                controller = self.primitives.env.get_eef_controller_state()
                if "error" in controller:
                    raise ValueError(controller["error"])
            control = EefControl(self.primitives)
            for name in sorted(optional_moves):
                definition = getattr(control, name)
                self.add_tool(
                    definition.with_handler(
                        partial(self._execute_primitive, name, definition)
                    )
                )
        if any(t["name"] == "rotate_axis" for t in selected):
            from robots.libero.research.orientation import OrientationControl

            controller = self.primitives.env.get_eef_controller_state()
            if "error" in controller:
                raise ValueError(controller["error"])
            definition = OrientationControl(self.primitives).rotate_axis
            self.add_tool(
                definition.with_handler(
                    partial(self._execute_primitive, "rotate_axis", definition)
                )
            )
        if placement_names:
            from robots.libero.research.placement import PlacementTools

            placement = PlacementTools(self.sensors, self.primitives)
            self.add_tool(placement.preview_placement)
            definition = placement.align_placement
            self.add_tool(
                definition.with_handler(
                    partial(self._execute_primitive, "align_placement", definition)
                )
            )
        originals = self._tools
        self._tools = {}
        generated = [t for t in selected if t["origin"] == "generated"]
        self.sandbox = Sandbox(sandbox_image) if generated else None
        self.selection = selected
        self.mask_client = RecordingSam3(self.primitives._sam3_client)
        self.primitives._sam3_client = self.mask_client
        for item in selected:
            name = item["name"]
            if item["origin"] == "native":
                original = originals[name]
                if self.planner_view_mode != "native":
                    if name == "view_env_state":
                        original = original.with_handler(
                            partial(self._planner_view, original)
                        )
                    if name in {"view_env_state", "read_image"}:
                        original = replace(
                            original, description=planner_view_description(name)
                        )
                if name == "segment":
                    original = original.with_handler(
                        partial(self.segment_recorded, original)
                    )
                self.add_tool(original)
            else:
                definition = {
                    k: item[k] for k in ("name", "description", "parameters", "source")
                }
                self.add_tool(
                    Tool(
                        name=name,
                        description=item["description"],
                        args_schema=_arguments_model(name, item["parameters"]),
                        _input_schema=item["parameters"],
                        handler=partial(self.generated, definition),
                        readonly=True,
                    )
                )

    def _image_payload(self, name, step, index):
        from io import BytesIO

        from PIL import Image

        image = self.state.load_bytes(name, step=step)
        with Image.open(BytesIO(image)) as opened:
            width, height = opened.size
        calibrated = name in {
            "agentview.png",
            "agentview_high.png",
            "wrist.png",
            "wrist_high.png",
        }
        policy = name == "agentview_policy.png"
        camera = (
            ("agentview" if name.startswith("agentview") else "wrist")
            if calibrated or policy
            else None
        )
        return image, {
            "index": index,
            "artifact": name,
            "camera": camera,
            "step": step,
            "width": width,
            "height": height,
            "coordinate_frame": "calibrated"
            if calibrated
            else "policy"
            if policy
            else "unclassified",
        }

    def _present_state(self, result):
        if self.planner_view_mode == "native" or "step" not in result.data:
            return result
        data = {**result.data, "planner_view_mode": self.planner_view_mode}
        images, views = [], []
        try:
            for index, name in enumerate(PLANNER_VIEW_ARTIFACTS):
                image, view = self._image_payload(name, data["step"], index)
                images.append(image)
                views.append(view)
        except OSError as exc:
            return ToolResult(
                data={
                    **data,
                    "error": f"Required planner image unavailable: {name}: {exc}",
                    "image_views": [],
                }
            )
        return ToolResult(data={**data, "image_views": views}, images=images)

    def _planner_view(self, original, **kwargs):
        return self._present_state(original(**kwargs))

    def get_env_state(self, **kwargs):
        return self._present_state(super().get_env_state(**kwargs))

    @property
    def planner_stop_result(self):
        if self._ended or self.solved() or self.primitives.env.truncated:
            return {
                "_finish": True,
                "environment_stopped": True,
                "status": "stopped",
                "summary": "Environment episode ended.",
            }
        return None

    def _execute_primitive(self, name, handler, **kwargs):
        if self.planner_stop_result is not None:
            return ToolResult(data={"error": "Environment episode ended"})
        return super()._execute_primitive(name, handler, **kwargs)

    @tool(readonly=True)
    def read_image(self, name: str, step: int = -1) -> ToolResult:
        """Read a saved PNG/JPEG observation artifact at the selected step."""
        record = self.state.get(step)
        if name not in record.artifacts or not name.endswith((".png", ".jpg", ".jpeg")):
            return ToolResult(data={"error": "Unknown image artifact"})
        if self.planner_view_mode != "native":
            image, view = self._image_payload(name, record.step_idx, 0)
            return ToolResult(
                data={"artifact": name, "step": record.step_idx, "image_views": [view]},
                images=[image],
            )
        return ToolResult(
            data={"artifact": name, "step": record.step_idx},
            images=[self.state.load_bytes(name, step=record.step_idx)],
        )

    def segment_recorded(self, original, **kwargs):
        self.mask_client.local.result = None
        result = original(**kwargs)
        data = self.mask_client.local.result
        if (
            data is not None
            and data.found
            and isinstance(data.mask, np.ndarray)
            and result.data.get("segment_artifact")
        ):
            step = result.data["step"]
            camera = result.data["camera"]
            image_name = result.data["image_artifact"]
            shape = self.state.load(image_name, step=step).shape[:2]
            if data.mask.shape != shape:
                raise ValueError("Native segmentation mask/image shape mismatch")
            name = result.data["segment_artifact"].replace(".json", "_mask.npz")
            self.state.save(name, data.mask, step=step)
            # Nearest-neighbour resampling is explicit; raw mask remains saved.
            h, w = self.state.load(f"{camera}.png", step=step).shape[:2]
            rows = np.minimum(
                ((np.arange(h) + 0.5) * shape[0] / h).astype(int), shape[0] - 1
            )
            cols = np.minimum(
                ((np.arange(w) + 0.5) * shape[1] / w).astype(int), shape[1] - 1
            )
            aligned = data.mask[rows[:, None], cols[None, :]]
            alignment = {
                "camera": camera,
                "mask_artifact": name,
                "source_artifact": image_name,
                "source_shape": list(shape),
                "resampling": "nearest pixel centres",
            }
            self.state.save(
                "mask_alignment_" + result.data["segment_artifact"],
                alignment,
                step=step,
            )
            with self.mask_lock:
                self.sensors.masks.setdefault(step, {})[name] = {
                    **alignment,
                    "mask": aligned,
                }
        return result

    def generated(self, definition, **params):
        params = {k: v for k, v in params.items() if v is not _OMITTED}
        with self.mask_lock:
            frames = self.sensors.frames()
        self.journal.append(
            "generated_input",
            {
                "name": definition["name"],
                "steps": [f["step"] for f in frames],
                "params": params,
                "sandbox_image": self.sandbox.image,
            },
        )
        return ToolResult(data=self.sandbox.run(definition, params, frames))

    def execute_tool(self, name, input_dict):
        call_id = uuid.uuid4().hex
        started = time.monotonic()
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
        generated = next(
            (
                t
                for t in self.selection
                if t["name"] == name and t["origin"] == "generated"
            ),
            None,
        )
        if generated:
            import json

            from rpent.dashboard.workbench import write_json

            with self.journal.lock:
                path = self.journal.root / "tool-invocations.json"
                invoked = json.loads(path.read_text()) if path.exists() else []
                write_json(path, sorted(set(invoked + [generated["version"]])))
        if result.data.get("_finish"):
            self._ended = True
        return result


def availability_prompt(selected, *, planner_view_mode="native"):
    names = ", ".join(t["name"] for t in selected)
    eef_guidance = (
        "Use translate_to for position-only moves while retaining the gripper target. "
        "Inspect returned images and pose; use an enabled gripper tool when the fingers must change.\n\n"
        if any(t["name"] == "translate_to" for t in selected)
        else "Use the latest images and EEF pose to choose the next short move_eef target. "
        "Revise it using returned images, measured pose and object motion; EEF arrival is not task completion.\n\n"
        if any(t["name"] == "move_eef" for t in selected)
        else ""
    )
    rotation_guidance = (
        "Use rotate_axis for relative world-axis rotation while retaining position "
        "and the gripper target. Inspect returned images and pose errors before "
        "the next move.\n\n"
        if any(t["name"] == "rotate_axis" for t in selected)
        else ""
    )
    placement_guidance = (
        "For placing a held object on a plate or into an open container, "
        "preview_placement selects a visible target region and includes the held-feature offset. "
        "Inspect its O/P/R overlay, then use align_placement with that preview_id; "
        "reselect incorrect marks. Recheck the returned images before lowering or releasing.\n\n"
        if {"preview_placement", "align_placement"} <= {t["name"] for t in selected}
        else ""
    )
    presentation = (
        "Native observations and action feedback remain unchanged. "
        if planner_view_mode == "native"
        else "Stored observations and VLA inputs remain unchanged. "
        "View and action images are ordered by image_views. "
        "For sampling, use a calibrated view's camera, step and pixel size. "
    )
    return (
        "EXPERIMENT TOOL SELECTION (overrides references to unavailable tools in the following guides): "
        f"Only these tools are enabled: {names}. Do not call any other tool or use shell/files/network to bypass this selection. "
        "Skip guide steps that require disabled tools. "
        + presentation
        + "Generated perception tools compute evidence, not task success.\n\n"
        + eef_guidance
        + rotation_guidance
        + placement_guidance
    )
