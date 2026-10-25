# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Selectable UniVTAC tools with recorded sensor frames and isolated programs."""

import hashlib
import inspect
import threading
import time
import uuid
from functools import partial
from pathlib import Path

import numpy as np

from robots.libero.research.library import Sandbox, digest, validate_tools
from robots.libero.research.native import _OMITTED, _arguments_model
from robots.univtac.perception import tactile_statistics
from rpent.dashboard.workbench import RunJournal, write_json
from rpent.session import EnvState
from rpent.tools import Tool, ToolResult, iter_tools, tool
from rpent.tools.common import CommonTools
from rpent.tools.toolkit import Toolkit


def native_catalog() -> list[dict]:
    result = []
    declarations = list(iter_tools(UniVTACToolkit)) + [CommonTools.finish]
    for declaration in declarations:
        source = inspect.getsource(declaration.handler)
        result.append(
            {
                "id": f"native:{declaration.name}",
                "name": declaration.name,
                "origin": "native",
                "category": "control"
                if declaration.name == "move_eef"
                else "auxiliary"
                if declaration.name == "finish"
                else "perception",
                "description": declaration.description,
                "parameters": declaration.input_schema,
                "version": hashlib.sha256(source.encode()).hexdigest(),
                "source": source,
                "required": declaration.name == "finish",
                "dependencies": [],
                "validation": "native",
                "input_contract": "Recorded UniVTAC sensor data; no simulator object state.",
                "example": None,
            }
        )
    return result


def validate_selection(selected):
    """Check a frozen allowlist before starting the simulator or Docker."""
    catalog = {item["name"]: item for item in native_catalog()}
    names = [item["name"] for item in selected]
    if "finish" not in names or len(names) != len(set(names)):
        raise ValueError("Select finish and at most one version per tool")
    for item in selected:
        missing = set(item.get("dependencies", [])) - set(names)
        if missing:
            raise ValueError(f"Missing tool dependencies: {sorted(missing)}")
        if item["origin"] == "native":
            current = catalog.get(item["name"])
            if current is None or any(
                item.get(key) != current[key]
                for key in ("version", "source", "parameters", "description")
            ):
                raise ValueError(f"Native tool changed since selection: {item['name']}")
        elif item["origin"] == "generated":
            definition = {
                k: item[k] for k in ("name", "description", "parameters", "source")
            }
            validate_tools([definition])
            if item["version"] != digest([definition]):
                raise ValueError(
                    f"Generated tool version does not match source: {item['name']}"
                )
        else:
            raise ValueError("Tool origin must be native or generated")


class UniVTACToolkit(Toolkit):
    planner_tools_only = True
    model_request_timeout_s = 180.0

    def __init__(
        self,
        *,
        env,
        output_dir,
        dashboard_events,
        memory,
        selected=None,
        journal=None,
        sandbox_image="embodied-sensor:pilot",
    ):
        self.env = env
        self.journal = journal or RunJournal(output_dir)
        self._capture_lock = threading.RLock()
        self._pending = []
        self._stopped = False
        self._evaluator = {}
        super().__init__(
            dashboard_events=dashboard_events,
            state=EnvState(Path(output_dir)),
            memory=memory,
        )
        # Common file tools could expose evaluator artifacts in this directory.
        finish = self._tools["finish"]
        self._tools = {}
        self.add_tool(finish)
        self.add_tools(iter_tools(self))
        available = self._tools
        self._tools = {}
        self.selection = native_catalog() if selected is None else selected
        validate_selection(self.selection)
        self.sandbox = (
            Sandbox(sandbox_image)
            if any(t["origin"] == "generated" for t in self.selection)
            else None
        )
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
        self._record(self.env.last_obs)
        self._update_evaluator()

    def _save_tree(self, value, prefix):
        if isinstance(value, np.ndarray):
            suffix = (
                ".png"
                if value.dtype == np.uint8
                and value.ndim == 3
                and value.shape[-1] in (3, 4)
                else ".npz"
            )
            name = prefix + suffix
            if self.state.save(name, value) is None:
                raise OSError(f"Failed to record sensor artifact: {name}")
            return {"artifact": name}
        if isinstance(value, dict):
            return {k: self._save_tree(v, f"{prefix}_{k}") for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._save_tree(v, f"{prefix}_{i}") for i, v in enumerate(value)]
        return value.item() if isinstance(value, np.generic) else value

    def _load_tree(self, value, step):
        if isinstance(value, dict):
            if set(value) == {"artifact"}:
                return self.state.load(value["artifact"], step=step)
            return {k: self._load_tree(v, step) for k, v in value.items()}
        if isinstance(value, list):
            return [self._load_tree(v, step) for v in value]
        return value

    def _tactile_previews(self, frame):
        """Keep native Taxim arrays; add RGB8 display copies without rescaling."""
        previews = {}
        for side in ("left", "right"):
            sensor = frame.get("tactile", {}).get(side, {})
            for kind in ("rgb", "reference_rgb"):
                if kind not in sensor:
                    continue
                raw = np.asarray(sensor[kind])
                name = f"sensor_tactile_{side}_{kind}.png"
                metadata = previews[name] = {
                    "source_artifact": f"sensor_tactile_{side}_{kind}"
                    + (".png" if raw.dtype == np.uint8 else ".npz"),
                    "source_dtype": str(raw.dtype),
                    "source_range": [0, 255],
                    "encoding": "RGB8 PNG",
                    "conversion": "clip to [0,255], round to nearest, cast uint8; no rescaling",
                }
                # Native Taxim defines RGB in [0,255], including float tensors.
                # A missing/invalid image must not become an invented black one.
                if raw.ndim != 3 or raw.shape[-1] != 3 or not np.isfinite(raw).all():
                    metadata["error"] = "Preview unavailable: expected finite HxWx3 RGB"
                    continue
                metadata["clipped_values"] = int(((raw < 0) | (raw > 255)).sum())
                if raw.dtype != np.uint8:
                    image = np.rint(np.clip(raw, 0, 255)).astype(np.uint8)
                    if self.state.save(name, image) is None:
                        raise OSError(f"Failed to record tactile preview: {name}")
        return previews

    def _record(
        self, observation, command=None, result=None, elapsed_s=None, publish=True
    ):
        # Only the simulator's explicit sensor contract is persisted here.
        keys = (
            "cameras",
            "tactile",
            "state",
            "timestamp",
            "simulation_time_s",
            "physics_dt",
            "control_step",
            "physics_step",
            "pose_frame",
            "eef_frame",
            "gripper_units",
        )
        frame = {k: observation[k] for k in keys if k in observation}
        state = {
            k: v.tolist() if isinstance(v, np.ndarray) else v
            for k, v in frame.get("state", {}).items()
        }
        with self.state.record_step(
            state=state, command=command, result=result, elapsed_s=elapsed_s
        ) as step:
            frame["step"] = step
            saved = self._save_tree(frame, "sensor")
            saved["image_previews"] = self._tactile_previews(frame)
            if self.state.save("sensor_frame.json", saved) is None:
                raise OSError("Failed to record sensor frame manifest")
        if publish:
            self._publish_step(self.state.get(step))
        return self._observation_result(step)

    def _observation_result(self, step):
        saved = self.state.load("sensor_frame.json", step=step)
        images, names = [], []
        for name in self.state.get(step).artifacts:
            if name.endswith(".png") and not name.endswith("_reference_rgb.png"):
                images.append(self.state.load_bytes(name, step=step))
                names.append(name)
        return ToolResult(
            data={
                "step": step,
                "state": self.state.get(step).state,
                "images": names,
                "sensors": saved,
                "control_result": self.state.get(step).result,
            },
            images=images,
        )

    def _frame(self, step=-1):
        record = self.state.get(step)
        return self._load_tree(
            self.state.load("sensor_frame.json", step=record.step_idx), record.step_idx
        )

    def _update_evaluator(self):
        self._evaluator = self.env.evaluator_state()
        self._stopped |= bool(self._evaluator.get("done"))
        write_json(self.journal.root / "evaluator.json", self._evaluator)
        if self._evaluator.get("video_path"):
            video = Path(self._evaluator["video_path"]).resolve()
            destination = self.journal.root / "episode.mp4"
            if (
                video.is_relative_to(self.journal.root.resolve())
                and video.is_file()
                and not destination.exists()
            ):
                destination.symlink_to(video)

    @property
    def planner_stop_result(self):
        if self._stopped:
            return {
                "_finish": True,
                "environment_stopped": True,
                "status": "stopped",
                "summary": "Environment episode ended.",
            }
        return None

    @tool(readonly=True)
    def observe(self) -> ToolResult:
        """Return the latest recorded camera/tactile images and measured hand pose without advancing physics."""
        with self._capture_lock:
            return self._observation_result(self.state.latest_record().step_idx)

    @tool(readonly=True)
    def read_image(self, name: str, step: int = -1) -> ToolResult:
        """Read an image listed in a recorded observation, including tactile reference images."""
        record = self.state.get(step)
        if name not in record.artifacts or not name.endswith(".png"):
            return ToolResult(data={"error": "Unknown recorded image"})
        return ToolResult(
            data={
                "step": record.step_idx,
                "artifact": name,
                "image_metadata": self.state.load(
                    "sensor_frame.json", step=record.step_idx
                )
                .get("image_previews", {})
                .get(name),
            },
            images=[self.state.load_bytes(name, step=record.step_idx)],
        )

    @tool(readonly=True)
    def tactile_stats(self, step: int = -1) -> ToolResult:
        """Compute bilateral image change and marker displacement from one recorded frame.

        Reports image/reference difference and displacement in pixels, not force,
        contact success or insertion direction. Reference kind is explicit.
        """
        return ToolResult(data=tactile_statistics(self._frame(step)))

    @tool(readonly=True)
    def depth_points(
        self, camera: str, pixels_rc: list[list[int]], step: int = -1
    ) -> ToolResult:
        """Read metric depth at up to 32 [row,column] pixels in a recorded camera's depth resolution."""
        if not 1 <= len(pixels_rc) <= 32:
            raise ValueError("Select 1..32 pixels")
        frame = self._frame(step)
        sensor = frame["cameras"][camera]
        if "depth" not in sensor:
            return ToolResult(data={"error": "Depth not recorded for this camera"})
        depth = np.asarray(sensor["depth"]).squeeze()
        if depth.ndim != 2:
            raise ValueError("Expected a two-dimensional depth map")
        values = []
        for pixel in pixels_rc:
            if len(pixel) != 2 or not (
                0 <= pixel[0] < depth.shape[0] and 0 <= pixel[1] < depth.shape[1]
            ):
                raise ValueError("Pixel outside recorded depth resolution")
            value = float(depth[tuple(pixel)])
            values.append(value if np.isfinite(value) and value > 0 else None)
        return ToolResult(
            data={
                "step": frame["step"],
                "camera": camera,
                "image_size": list(depth.shape),
                "pixels_rc": pixels_rc,
                "depth_m": values,
                "calibration": {
                    key: value.tolist() if isinstance(value, np.ndarray) else value
                    for key, value in sensor["calibration"].items()
                }
                if "calibration" in sensor
                else "not_recorded",
            }
        )

    @tool
    def move_eef(self, poses: list[list[float]]) -> ToolResult:
        """Execute 1..5 short world-frame Panda-hand targets, then observe actual motion.

        Each target is [x,y,z,qw,qx,qy,qz,gripper]: metres, unit wxyz quaternion,
        gripper 0 closed to 1 open. Local IK bounds joint changes. This is
        position control, not force control or a collision-free path guarantee.
        """
        if self._stopped:
            return ToolResult(data={"error": "Environment episode ended"})
        if not 1 <= len(poses) <= 5:
            raise ValueError("Supply 1..5 target poses")
        self.raise_if_cancelled()
        observations, _, terminated, truncated, info = self.env.chunk_step(
            poses, return_all_frames=True
        )
        self._pending = (
            observations if isinstance(observations, list) else [observations]
        )
        self._stopped = bool(terminated or truncated)
        return ToolResult(data=info)

    def get_env_state(self, *, command, result, elapsed_s):
        with self._capture_lock:
            observations = self._pending or [self.env.get_observation()]
            self._pending = []
            for index, observation in enumerate(observations):
                last = self._record(
                    observation,
                    command=command if index == 0 else None,
                    result=result,
                    elapsed_s=elapsed_s if index == 0 else None,
                    publish=index < len(observations) - 1,
                )
            self._update_evaluator()
            return last

    def _generated(self, definition, **params):
        params = {k: v for k, v in params.items() if v is not _OMITTED}
        with self._capture_lock:
            frames = [self._frame(r.step_idx) for r in self.state.records()[-4:]]
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
        call_id, started = uuid.uuid4().hex, time.monotonic()
        self.journal.append(
            "tool_request", {"call_id": call_id, "name": name, "arguments": input_dict}
        )
        result = super().execute_tool(name, input_dict)
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
        if result.data.get("_finish"):
            self._stopped = True
        if any(
            t["name"] == name and t["origin"] == "generated" for t in self.selection
        ):
            import json

            with self.journal.lock:
                path = self.journal.root / "tool-invocations.json"
                versions = json.loads(path.read_text()) if path.exists() else []
                versions += [t["version"] for t in self.selection if t["name"] == name]
                write_json(path, sorted(set(versions)))
        return result

    def solved(self) -> bool:
        return bool(self._evaluator.get("official_success", False))

    def close(self) -> None:
        super().close()
        self.env.close()
