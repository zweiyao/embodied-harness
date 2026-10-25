# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Pinned UniVTAC task lifecycle, with private evaluator records.

Isaac/TacEx imports happen only after SimulationApp starts. Constructing this
object does not reset a task or consume an experiment episode.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import random
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np

from .control import (
    CHUNK_LIMIT,
    COMMAND_LIMIT,
    PandaController,
    native_status,
    validate_command,
)
from .observations import array, sensor_observation

UNIVTAC_COMMIT = "0dafa10262e22f486f160a55d6f11aeab12d8e7b"
TASKS = ("insert_hole", "insert_tube", "pull_out_key")


def json_value(value):
    """Serialize evaluator measurements without tensor/device objects."""
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if hasattr(value, "detach") or isinstance(value, np.ndarray):
        return array(value).tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if callable(value):
        return f"{value.__module__}.{value.__qualname__}"
    raise TypeError(f"Unsupported evaluator value: {type(value).__name__}")


def save_native_frame(path, native):
    """Private numeric archive, including truth; never used as a model frame."""
    flattened = {}

    def visit(value, key):
        if isinstance(value, dict):
            for name, item in value.items():
                visit(item, f"{key}/{name}" if key else str(name))
        elif value is not None:
            values = array(value)
            if values.dtype.hasobject:
                raise TypeError(f"Unsupported raw observation type at {key}")
            flattened[key] = values

    visit(native, "")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **flattened)
    temporary.replace(path)


def recording_task_class(native_class):
    """Observe after native stepping; do not change physics or task predicates."""

    class RecordingTask(native_class):
        def _step(self, is_save=True):
            before = int(getattr(self, "step_count", 0))
            super()._step(is_save=is_save)
            if int(self.step_count) == before:
                return
            records_video = (
                is_save
                and not self.in_pre_move
                and self.mode != "eval_test"
                and self.cfg.video_frequency > 0
                and self.step_count % self.cfg.video_frequency == 0
            )
            if records_video:
                self._rpent_video_frames = getattr(self, "_rpent_video_frames", 0) + 1
            if getattr(self, "_rpent_recording", False):
                observation = self._get_observations()
                observation["video_frame_index"] = self._rpent_video_frames - 1
                save_native_frame(
                    self._rpent_archive / f"physics-{int(self.step_count):08d}.npz",
                    observation,
                )

    return RecordingTask


class UniVTACBackend:
    def __init__(
        self, *, root, output_dir, task_name="insert_hole", seed=0, device="cuda:0"
    ):
        if task_name not in TASKS:
            raise ValueError(f"Supported tasks: {TASKS}")
        self.root = Path(root).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        commit = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True
        ).strip()
        if commit != UNIVTAC_COMMIT:
            raise RuntimeError(f"Expected UniVTAC {UNIVTAC_COMMIT}, found {commit}")
        self.task_name, self.seed, self.device = task_name, int(seed), device
        self.app = self.task = self.controller = None
        self.references = {}
        self.scene_components = None
        self.physics_start = 0
        self.run_dir = None
        self.last_receipt = {}
        self.attempted_commands = 0
        self.recording_finished = False

    def start_app(self):
        if self.app is not None:
            return
        # Native VideoHandler resolves ffmpeg from this process's PATH.
        os.environ["PATH"] = (
            str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
        )
        sys.path.insert(0, str(self.root))
        from isaaclab.app import AppLauncher

        self.app = AppLauncher(
            {
                "headless": True,
                "enable_cameras": True,
                "device": self.device,
                "livestream": 0,
            }
        ).app

    def reset(self, *, task_name=None, seed=None):
        requested = task_name or self.task_name
        if requested != self.task_name:
            raise ValueError("Start a new server when switching UniVTAC task classes")
        self.seed = self.seed if seed is None else int(seed)
        self.start_app()
        self.run_dir = (
            self.output_dir / f"{self.task_name}-s{self.seed}-{uuid.uuid4().hex}"
        )
        self.run_dir.mkdir(parents=True, exist_ok=False)
        module = importlib.import_module(f"envs.{self.task_name}")
        if (
            Path(module.__file__).resolve()
            != self.root / "envs" / f"{self.task_name}.py"
        ):
            raise RuntimeError("Wrong envs package imported")
        if self.task is None:
            cfg = module.TaskCfg()
            cfg.seed = self.seed
            cfg.save_dir = self.run_dir / "native"
            cfg.sim.device = self.device
            cfg.scene.num_envs = 1
            cfg.sim.enable_scene_query_support = True
            cfg.tactile_sensor_type = "gsmini"
            # TiledCamera otherwise returns its initialization pose even after
            # the wrist moves, making RGB/depth world coordinates incorrect.
            for camera in cfg.cameras:
                camera.update_latest_camera_pose = True
            cfg.obs_data_type = {
                "camera": ["rgb", "depth"],
                "tactile": ["rgb", "rgb_marker", "marker", "depth", "pose"],
                "embodiment": ["joint", "ee"],
                "actor": True,
            }
            cfg.save_frequency = cfg.video_frequency = 1
            cfg.render_frequency = 0
            cfg.video_size = (1120, 320)
            self.task = recording_task_class(module.Task)(cfg, mode="eval")
        else:
            self.finish_recording()
            self.task.cfg.save_dir = self.run_dir / "native"
        if self.task.cfg.step_lim != COMMAND_LIMIT:
            raise RuntimeError(
                "Native command limit differs from reviewed 300-command protocol"
            )
        if (
            abs(float(self.task.cfg.sim.dt) - 1 / 120) > 1e-9
            or self.task.cfg.decimation != 1
        ):
            raise RuntimeError(
                "Native physics cadence differs from reviewed 120 Hz protocol"
            )
        instruction_file = self.root / "instructions" / f"{self.task_name}.json"
        instructions = json.loads(instruction_file.read_text())["seen"]
        # Native reset and pre_move remain intact: these tasks begin already held.
        self.task._rpent_recording = False
        self.task._rpent_video_frames = 0
        self.task.reset(seed=self.seed, instructions=instructions)
        self.physics_start = int(self.task.step_count)
        self.initial_video_frames = self.task._rpent_video_frames
        self.task._rpent_archive = self.run_dir / "evaluator-frames"
        self.controller = PandaController(self.task)
        native = self.task._get_observations()
        save_native_frame(self.task._rpent_archive / "initial.npz", native)
        self.references = {
            side: array(native["tactile"][f"{side}_tactile"]["rgb"])
            for side in ("left", "right")
        }
        self.scene_components = self._scene_components(native)
        (self.run_dir / "evaluator-scene.json").write_text(
            json.dumps(self.scene_components, indent=2, allow_nan=False)
        )
        self.last_receipt = {}
        self.attempted_commands = 0
        self.recording_finished = False
        self.task._rpent_recording = True
        return self.observation(), {"control_step": int(self.task.take_action_cnt)}

    def _require_task(self):
        if self.task is None or self.controller is None:
            raise RuntimeError("Reset the task before requesting observations/actions")

    def calibration(self):
        self._require_task()
        output = {}
        for name, camera in self.task._camera_manager.cameras.items():
            data = camera.data
            output[name] = {
                "intrinsics": array(data.intrinsic_matrices)[0],
                "position_w": array(data.pos_w)[0],
                "quaternion_wxyz": array(data.quat_w_ros)[0],
                "camera_convention": "ros_optical",
                "depth_units": "m",
                "height": camera.cfg.height,
                "width": camera.cfg.width,
            }
        return output

    def observation(self):
        self._require_task()
        self.task._update_render()
        return sensor_observation(
            self.task._get_observations(),
            self.controller.observer.observe_state(self.task),
            self.references,
            control_step=self.task.take_action_cnt,
            physics_step=int(self.task.step_count) - self.physics_start,
            calibration=self.calibration(),
        )

    def step(self, action):
        self._require_task()
        if (
            self.recording_finished
            or native_status(self.task)["done"]
            or self.attempted_commands >= COMMAND_LIMIT
        ):
            raise RuntimeError("Episode ended; no additional motion is allowed")
        action = validate_command(action)
        self.attempted_commands += 1
        receipt = self.controller.execute(action)
        receipt["attempted_commands"] = self.attempted_commands
        self.last_receipt = receipt
        status = native_status(self.task)
        # Rewards and success labels are evaluator-only. Generic stopped flag is
        # needed for the runner to stop; no native success truth enters obs/info.
        stopped = status["done"] or self.attempted_commands >= COMMAND_LIMIT
        return self.observation(), 0.0, stopped, False, dict(receipt)

    def chunk_step(self, actions, *, return_all_frames=False):
        if (
            not isinstance(actions, (list, tuple))
            or not 1 <= len(actions) <= CHUNK_LIMIT
        ):
            raise ValueError("A chunk must contain 1–5 short EEF commands")
        validated = [validate_command(action) for action in actions]
        frames, receipts = [], []
        result = None
        for action in validated:
            result = self.step(action)
            frames.append(result[0])
            receipts.append(result[4])
            if result[2] or not result[4]["exec_success"]:
                break
        observation, reward, terminated, truncated, _ = result
        return (
            frames if return_all_frames else observation,
            reward,
            terminated,
            truncated,
            {
                "commands": receipts,
                "executed_commands": sum(r["native_action_delta"] for r in receipts),
            },
        )

    def evaluator_state(self):
        self._require_task()
        status = native_status(self.task)
        exhausted = self.attempted_commands >= COMMAND_LIMIT
        return {
            **status,
            "done": status["done"] or exhausted,
            "attempted_commands": self.attempted_commands,
            "command_budget_exhausted": exhausted,
            "task": self.task_name,
            "seed": self.seed,
            "control_step": int(self.task.take_action_cnt),
            "physics_step": int(self.task.step_count) - self.physics_start,
            "pre_move_physics_steps": self.physics_start,
            "scene": self.scene_components,
            "restorable": False,
            "unrecorded_state": [
                "UIPC solver/contact warm-start state",
                "renderer RNG/internal state",
            ],
            "run_dir": str(self.run_dir),
            "video_path": str(self.task.save_video_path),
            "video_fps": 10,
            "initial_video_frames": self.initial_video_frames,
            "native_frames_dir": str(self.task._rpent_archive),
        }

    def _scene_components(self, native):
        import torch

        initial_sensor_hashes = {}
        for group in ("observation", "tactile"):
            for name, measurements in native[group].items():
                for kind in ("rgb", "depth", "marker"):
                    if kind not in measurements:
                        continue
                    values = array(measurements[kind])
                    initial_sensor_hashes[f"{group}/{name}/{kind}"] = {
                        "shape": list(values.shape),
                        "dtype": str(values.dtype),
                        "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                    }
        gels = {
            name: array(sensor.gelpad.data.nodal_pos_w)
            for name, sensor in self.task._tactile_manager.tactiles.items()
        }
        np.savez_compressed(self.run_dir / "evaluator-initial-gel.npz", **gels)
        assets = {}
        for root in (
            self.root / "assets",
            self.root / "third_party/TacEx/source/tacex_assets/tacex_assets/data",
        ):
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                    assets[str(path.relative_to(self.root))] = digest.hexdigest()
        if not assets:
            raise RuntimeError("No asset files found for scene fingerprint")
        return json_value(
            {
                "model": {
                    "benchmark_commit": UNIVTAC_COMMIT,
                    "task": self.task_name,
                    "sensor": "gsmini",
                },
                "state": {
                    "actors": native["actor"],
                    "robot": self.controller.observer.observe_state(self.task),
                    "pre_move_physics_steps": self.physics_start,
                    "gel_vertices_w": gels,
                    "restorable": False,
                    "unrecorded": [
                        "UIPC solver/contact warm-start state",
                        "renderer RNG/internal state",
                    ],
                },
                "physics": {
                    "dt": self.task.cfg.sim.dt,
                    "decimation": self.task.cfg.decimation,
                    "physx": self.task.cfg.sim.physx.to_dict(),
                    "uipc_contact": self.task.cfg.uipc_sim.contact.to_dict(),
                    "action_repeat": 2,
                    "command_limit": COMMAND_LIMIT,
                },
                "sensors": {
                    "camera_calibration": self.calibration(),
                    "initial_measurement_hashes": initial_sensor_hashes,
                    "tactile_reference_kind": "episode_initial_contact",
                },
                "rng": {
                    "seed": self.seed,
                    "task_rng": self.task.rng.bit_generator.state,
                    "torch_cpu": hashlib.sha256(
                        torch.get_rng_state().numpy().tobytes()
                    ).hexdigest(),
                    "torch_cuda": [
                        hashlib.sha256(state.cpu().numpy().tobytes()).hexdigest()
                        for state in torch.cuda.get_rng_state_all()
                    ],
                    "numpy_legacy": np.random.get_state(),
                    "python": random.getstate(),
                },
                "assets": assets,
            }
        )

    def finish_recording(self):
        """Flush video without closing Kit while an RPC reply is in flight."""
        self.recording_finished = True
        if (
            self.task is not None
            and getattr(self.task.video_handler, "ffmpeg", None) is not None
        ):
            self.task.video_handler.close()
        return {"recording_finished": True}

    def close(self):
        self.finish_recording()
        if self.task is not None:
            task, self.task = self.task, None
            task.close()
        if self.app is not None:
            app, self.app = self.app, None
            app.close()
