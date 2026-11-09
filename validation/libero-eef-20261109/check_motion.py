# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Bounded real-simulator integration check; writes evidence outside the repo."""

import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from robots.libero.eef_control import EefControl
from robots.libero.env_client import LiberoEnvClient
from robots.libero.env_server import LiberoEnvFacade, make_env
from robots.libero.tools import LiberoPrimitives
from rpent.utils.logging import init_output_dir


def main():
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=False)
    config_root = root / "libero-config"
    shutil.copytree(os.environ["LIBERO_CONFIG_PATH"], config_root)
    os.environ["LIBERO_CONFIG_PATH"] = str(config_root.resolve())
    init_output_dir(root)
    env = make_env(0, 0, "libero_10_task", enable_eef_control=True)
    facade = LiberoEnvFacade(env, meta={})

    class LocalRpc:
        def call(self, name, args=(), kwargs=None, **ignored):
            return facade._rpc[name](*args, **(kwargs or {}))

    report = {"passed": False, "checks": [], "native_success": False}
    try:
        client = LiberoEnvClient(LocalRpc(), expected_meta={})
        config = client.get_eef_controller_state()
        report["controller"] = config
        p = LiberoPrimitives(client, None, None, lambda: None)
        p.set_obs(client.last_obs)
        p.start_recording()
        control = EefControl(p)
        for kind in ("translation", "rotation"):
            for axis in range(3):
                raw = client.raw_obs()
                xyz = np.asarray(raw["robot0_eef_pos"])
                rotation = Rotation.from_quat(raw["robot0_eef_quat"])
                delta = np.eye(3)[axis] * (0.006 if kind == "translation" else 0.08)
                target_xyz = xyz + delta if kind == "translation" else xyz
                target_rot = (
                    Rotation.from_rotvec(delta) * rotation
                    if kind == "rotation"
                    else rotation
                )
                result = control.move_eef(
                    target_xyz.tolist(), target_rot.as_quat().tolist(), -1, 10
                )
                after = client.raw_obs()
                actual = (
                    np.asarray(after["robot0_eef_pos"]) - xyz
                    if kind == "translation"
                    else (
                        Rotation.from_quat(after["robot0_eef_quat"]) * rotation.inv()
                    ).as_rotvec()
                )
                error = result.data[
                    "position_error_m"
                    if kind == "translation"
                    else "orientation_error_rad"
                ]
                check = {
                    "kind": kind,
                    "axis": axis,
                    "before_error": float(np.linalg.norm(delta)),
                    "after_error": error,
                    "actual_delta": actual.tolist(),
                    "steps": result.data["steps_used"],
                }
                check["passed"] = bool(
                    actual @ delta > 0
                    and error < np.linalg.norm(delta)
                    and check["steps"] == 10
                )
                report["checks"].append(check)
                assert check["passed"], check
        raw = client.raw_obs()
        opening_before = float(np.abs(raw["robot0_gripper_qpos"]).sum())
        result = control.move_eef(
            raw["robot0_eef_pos"].tolist(), raw["robot0_eef_quat"].tolist(), 1, 10
        )
        opening_after = float(np.abs(client.raw_obs()["robot0_gripper_qpos"]).sum())
        report["gripper"] = {
            "before": opening_before,
            "after": opening_after,
            "steps": result.data["steps_used"],
        }
        assert opening_after < opening_before and result.data["steps_used"] == 10
        report["recorded_frames"] = p.recorded_frame_count()
        assert report["recorded_frames"] == 70
        report["native_success"] = client.terminated
        report["passed"] = True
    finally:
        facade.close()
        report["environment_closed"] = True
        (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
