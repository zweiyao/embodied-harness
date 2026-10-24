# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""RPent's existing RPC transport, served on Isaac's main thread."""

from __future__ import annotations

import argparse

import numpy as np

from rpent.robots.components.action_spec import box_action_spec
from rpent.robots.components.env_facade_base import BaseEnvFacade
from rpent.utils.rpc.main_thread_serve import MainThreadServeMixin

from .backend import TASKS, UNIVTAC_COMMIT, UniVTACBackend


class UniVTACEnvFacade(MainThreadServeMixin, BaseEnvFacade):
    def __init__(self, backend):
        self.backend = backend
        super().__init__()

    def _register_rpc(self):
        super()._register_rpc()
        self._rpc["env.raw_obs"] = self.backend.observation
        # Trusted experiment runner only; never include in the model tool list.
        self._rpc["env.evaluator_state"] = self.backend.evaluator_state
        self._rpc["env.close"] = self.backend.finish_recording

    def get_env_meta(self):
        return {
            "robot": "univtac",
            "task_name": self.backend.task_name,
            "seed": self.backend.seed,
            "benchmark_commit": UNIVTAC_COMMIT,
            "physics_hz": 120,
            "action_repeat": 2,
            "command_limit": 300,
            "chunk_limit": 5,
            "pose_frame": "world",
            "eef_frame": "panda_hand",
        }

    def get_action_spec(self):
        return {
            "default": box_action_spec(
                [-np.inf] * 3 + [-1] * 4 + [0],
                [np.inf] * 3 + [1] * 4 + [1],
                "Absolute Panda hand world pose [x,y,z,qw,qx,qy,qz,gripper]. "
                "Metres, wxyz; gripper 0=closed, 1=single-finger opening 0.039m. "
                "One command uses continuous IK (max joint change 0.15rad) and "
                "up to two 120Hz physics steps. Batches contain 1–5 commands.",
            )
        }

    def reset(self, *, task_name=None, seed=None):
        return self.backend.reset(task_name=task_name, seed=seed)

    def step(self, action):
        return self.backend.step(action)

    def chunk_step(self, actions, *, return_all_frames=False):
        return self.backend.chunk_step(actions, return_all_frames=return_all_frames)

    def get_task_language(self):
        self.backend._require_task()
        return self.backend.task.instruction

    def get_camera_meta(self, camera_name="head", height=None, width=None):
        calibration = self.backend.calibration()[camera_name]
        if height not in (None, calibration["height"]) or width not in (
            None,
            calibration["width"],
        ):
            raise ValueError(
                "UniVTAC exposes native camera resolution; resizing is not implicit"
            )
        return calibration

    def render_camera(self, camera_name="head", height=None, width=None, depth=False):
        self.get_camera_meta(camera_name, height, width)
        frame = self.backend.observation()["cameras"][camera_name]
        return frame["depth" if depth else "rgb"]

    def close(self):
        self.backend.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", required=True, help="Pinned independent UniVTAC checkout"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Private native/evaluator archive"
    )
    parser.add_argument("--task-name", choices=TASKS, default="insert_hole")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18760)
    parser.add_argument("--transport", choices=("socket", "http"), default="socket")
    parser.add_argument("--parent-watch", action="store_true")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost"):
        parser.error("Evaluator RPC must bind to remote loopback only")
    backend = UniVTACBackend(
        root=args.root,
        output_dir=args.output_dir,
        task_name=args.task_name,
        seed=args.seed,
        device=args.device,
    )
    UniVTACEnvFacade(backend).serve(
        transport=args.transport,
        host=args.host,
        port=args.port,
        parent_watch=args.parent_watch,
    )


if __name__ == "__main__":
    main()
