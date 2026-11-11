# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Finite real-simulator comparison; raw traces/images remain in its output root."""

import hashlib
import json
import os
import signal
import sys
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    assert Path(os.environ["LIBERO_CONFIG_PATH"]).resolve() == root / "libero-config"
    proxies = [name for name in os.environ if name.lower().endswith("_proxy")]
    assert not proxies, proxies
    config_path = root / "libero-config/config.yaml"
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()

    # The launcher sets the private config path before this interpreter starts.
    import imageio.v2 as imageio
    import numpy as np
    import yaml
    from scipy.spatial.transform import Rotation

    from robots.libero import eef_control
    from robots.libero.eef_control import ControllerObservation, EefControl
    from robots.libero.env_client import LiberoEnvClient
    from robots.libero.env_server import LiberoEnvFacade, make_env
    from robots.libero.tools import LiberoPrimitives
    from rpent.utils.config import get_repo_root
    from rpent.utils.logging import init_output_dir

    config = yaml.safe_load(config_path.read_text())
    assert (
        config["benchmark_root"]
        == json.loads((root / "preparation.json").read_text())["benchmark_root"]
    )
    source_root = Path(os.environ["RPENT_REPO_ROOT"]).resolve()
    assert get_repo_root().resolve() == source_root
    module_paths = {
        "eef_control": str(Path(eef_control.__file__).resolve()),
        "env_server": str(Path(sys.modules[make_env.__module__].__file__).resolve()),
    }
    assert all(Path(path).is_relative_to(source_root) for path in module_paths.values())

    class ProbeObservation(ControllerObservation):
        @property
        def probe_bddl_path(self):
            return str(self.env.env.bddl_file_name)

        @property
        def probe_gripper_state(self):
            gripper = self.env.robots[0].gripper["right"]
            return {
                "class": type(gripper).__name__,
                "current_action": np.asarray(gripper.current_action).tolist(),
            }

    def wrap(factory):
        return ProbeObservation(factory())

    # Per-process readonly instrumentation; no source or existing service changes.
    eef_control.with_controller_observation = wrap

    def timeout(signum, frame):
        raise TimeoutError("Probe watchdog expired")

    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGTERM, timeout)
    signal.alarm(300)
    report = {
        "passed": False,
        "model_requests": 0,
        "cases": [],
        "pid": os.getpid(),
        "source_root": str(source_root),
        "module_paths": module_paths,
    }
    owned = {}
    facade = None
    env = None

    def remember_children():
        pending = [os.getpid()]
        while pending:
            parent = pending.pop()
            path = Path(f"/proc/{parent}/task/{parent}/children")
            if not path.exists():
                continue
            for pid in map(int, path.read_text().split()):
                stat = Path(f"/proc/{pid}/stat")
                if stat.exists():
                    owned[str(pid)] = stat.read_text().split()[21]
                    pending.append(pid)

    try:
        init_output_dir(root)
        env = make_env(
            0, 0, "libero_10_task", max_episode_steps=200, enable_eef_control=True
        )
        facade = LiberoEnvFacade(env, meta={})
        remember_children()

        class LocalRpc:
            def call(self, name, args=(), kwargs=None, **ignored):
                return facade._rpc[name](*args, **(kwargs or {}))

        client = LiberoEnvClient(LocalRpc(), expected_meta={})
        bddl = Path(env.env.workers[0].get_env_attr("probe_bddl_path")).resolve()
        assert bddl.is_relative_to(Path(config["bddl_files"]).resolve())
        report["actual_task"] = {
            "suite": "libero_10_task",
            "task": 0,
            "seed": 0,
            "bddl_path": str(bddl),
            "bddl_sha256": hashlib.sha256(bddl.read_bytes()).hexdigest(),
        }

        def robot_state():
            raw = client.raw_obs()
            grip = env.env.workers[0].get_env_attr("probe_gripper_state")
            return {
                "eef_xyz": np.asarray(raw["robot0_eef_pos"]).tolist(),
                "eef_quat_xyzw": np.asarray(raw["robot0_eef_quat"]).tolist(),
                "gripper_qpos": np.asarray(raw["robot0_gripper_qpos"]).tolist(),
                "gripper": grip,
            }

        report["task_language"] = client.get_task_language()
        report["config"] = config
        for label, grip_command, warm_steps in [
            ("open", -1, 5),
            ("closed", 1, 10),
            ("partial", 1, 1),
        ]:
            pair = []
            for variant in ["old", "B"]:
                client.reset()
                p = LiberoPrimitives(client, None, None, lambda: None)
                p.set_obs(client.last_obs)
                p.start_recording()
                p.set_gripper(gripper=grip_command, steps=warm_steps)
                before = robot_state()
                target = np.asarray(before["eef_xyz"]) + [0, 0, 0.025]
                traces = []
                inner_step = p._step_env

                def traced_step(action):
                    inner_step(action)
                    traces.append(
                        {"action": np.asarray(action).tolist(), **robot_state()}
                    )

                p._step_env = traced_step
                case_root = root / (label + "-" + variant)
                case_root.mkdir()
                imageio.imwrite(case_root / "before.png", p._last_obs["main_images"])
                frame_start = p.recorded_frame_count()
                result = (
                    p.move_to(target.tolist(), gripper=0.0)
                    if variant == "old"
                    else EefControl(p).translate_to(target.tolist())
                )
                after = robot_state()
                frame_count = p.recorded_frame_count() - frame_start
                assert frame_count == len(traces) > 0
                for step in traces:
                    np.testing.assert_array_equal(step["action"][3:], [0, 0, 0, 0])
                    np.testing.assert_array_equal(
                        step["gripper"]["current_action"],
                        before["gripper"]["current_action"],
                    )
                np.testing.assert_array_equal(
                    after["gripper"]["current_action"],
                    before["gripper"]["current_action"],
                )
                previous_count = len(traces)
                arrived = EefControl(p).translate_to(after["eef_xyz"])
                assert len(traces) == previous_count and arrived.data["steps_used"] == 1
                imageio.imwrite(case_root / "after.png", p._last_obs["main_images"])
                imageio.mimwrite(case_root / "frames.mp4", p.stop_recording(), fps=20)
                (case_root / "trace.json").write_text(
                    json.dumps(
                        {"before": before, "steps": traces, "after": after}, indent=2
                    )
                    + "\n"
                )
                rotation_change = (
                    Rotation.from_quat(after["eef_quat_xyzw"])
                    * Rotation.from_quat(before["eef_quat_xyzw"]).inv()
                ).magnitude()
                case = {
                    "gripper_case": label,
                    "variant": variant,
                    "warmup_steps": warm_steps,
                    "actual_motion_steps": frame_count,
                    "result": result.data,
                    "rotation_change_rad": float(rotation_change),
                    "initial_gripper_target": before["gripper"]["current_action"],
                    "gripper_class": before["gripper"]["class"],
                    "qpos_before": before["gripper_qpos"],
                    "qpos_after": after["gripper_qpos"],
                    "at_target_actual_steps": 0,
                    "at_target_reported_steps": arrived.data["steps_used"],
                }
                report["cases"].append(case)
                pair.append((before, traces, after))
                remember_children()
            for field in ["eef_xyz", "eef_quat_xyzw", "gripper_qpos"]:
                np.testing.assert_allclose(
                    pair[0][0][field], pair[1][0][field], atol=1e-7, rtol=0
                )
                np.testing.assert_allclose(
                    pair[0][2][field], pair[1][2][field], atol=1e-7, rtol=0
                )
            np.testing.assert_array_equal(
                pair[0][0]["gripper"]["current_action"],
                pair[1][0]["gripper"]["current_action"],
            )
            assert len(pair[0][1]) == len(pair[1][1])
            for old_step, new_step in zip(pair[0][1], pair[1][1], strict=True):
                for field in ["action", "eef_xyz", "eef_quat_xyzw", "gripper_qpos"]:
                    np.testing.assert_allclose(
                        old_step[field], new_step[field], atol=1e-7, rtol=0
                    )
            assert (
                report["cases"][-1]["result"]["steps_used"]
                == report["cases"][-2]["result"]["steps_used"]
            )
        report["passed"] = True
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        remember_children()
        try:
            if facade is not None:
                facade.close()
            elif env is not None:
                env.env.close()
        except BaseException as exc:
            report["passed"] = False
            report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        signal.alarm(0)
        report["facade_closed"] = facade is not None and facade._closed
        report["owned_children_start_ticks"] = owned
        report["private_config_unchanged"] = (
            hashlib.sha256(config_path.read_bytes()).hexdigest() == config_hash
        )
        report["proxy_variables_present"] = proxies
        report["purpose"] = (
            "Interface comparison only; not a scored task or holding test."
        )
        report["gripper_case_labels"] = (
            "Warmup command labels; measured qpos is reported separately and not assumed settled."
        )
        (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
