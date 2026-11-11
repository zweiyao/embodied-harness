# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Finite selected-tool rotation probe with robot-only frame evidence."""

import hashlib
import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace


def main():
    root = Path(sys.argv[1]).resolve()
    source = Path(os.environ["RPENT_REPO_ROOT"]).resolve()
    config = root / "libero-config/config.yaml"
    assert Path(os.environ["LIBERO_CONFIG_PATH"]).resolve() == config.parent
    before_config = hashlib.sha256(config.read_bytes()).hexdigest()
    assert not any(
        os.environ.get(name)
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        )
    )

    import numpy as np
    from scipy.spatial.transform import Rotation

    from robots.libero import eef_control
    from robots.libero.env_client import LiberoEnvClient
    from robots.libero.env_server import LiberoEnvFacade, make_env
    from robots.libero.research import orientation
    from robots.libero.research.manual import ManualToolkit
    from rpent.dashboard.workbench import RunJournal, native_catalog
    from rpent.memory import MemoryManager
    from rpent.utils.config import get_repo_root
    from rpent.utils.logging import init_output_dir

    assert get_repo_root().resolve() == source
    assert Path(orientation.__file__).resolve().is_relative_to(source)

    class ProbeObservation(eef_control.ControllerObservation):
        @property
        def probe_robot_frame(self):
            robot = self.env.robots[0]
            sim = robot.sim
            body_name = robot.robot_model.eef_name["right"]
            site_id = robot.eef_site_id["right"]
            controller = robot.part_controllers["right"]
            gripper = robot.gripper["right"]
            return {
                "robot_class": type(robot).__name__,
                "gripper_class": type(gripper).__name__,
                "body_name": body_name,
                "site_name": sim.model.site_id2name(site_id),
                "site_id": int(site_id),
                "controller_ref_name": controller.ref_name,
                "controller_ref_site_id": int(
                    sim.model.site_name2id(controller.ref_name)
                ),
                "body_quat_wxyz": np.asarray(
                    sim.data.get_body_xquat(body_name)
                ).tolist(),
                "site_rotation": np.asarray(sim.data.site_xmat[site_id])
                .reshape(3, 3)
                .tolist(),
                "site_position": np.asarray(sim.data.site_xpos[site_id]).tolist(),
                "gripper_target": np.asarray(gripper.current_action).tolist(),
            }

    def wrap(factory):
        return ProbeObservation(factory())

    # Process-local instrumentation; installed source and other services unchanged.
    eef_control.with_controller_observation = wrap
    owned = {}

    def remember_children():
        pending = [os.getpid()]
        while pending:
            pid = pending.pop()
            children = Path(f"/proc/{pid}/task/{pid}/children")
            if children.exists():
                for child in map(int, children.read_text().split()):
                    stat = Path(f"/proc/{child}/stat")
                    if stat.exists():
                        owned[str(child)] = stat.read_text().split()[21]
                        pending.append(child)

    def stop(signum, frame):
        raise TimeoutError("R probe watchdog expired")

    signal.signal(signal.SIGALRM, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.alarm(300)
    report = {
        "passed": False,
        "transform_gate_passed": False,
        "source_root": str(source),
        "pid": os.getpid(),
        "model_requests": 0,
        "vla_requests": 0,
        "vla_predictions": 0,
        "enable_eef_control": True,
        "purpose": "Robot interface only; no object manipulation or task-success claim",
        "cases": [],
    }
    env = facade = toolkit = None
    trace = []
    try:
        init_output_dir(root)
        env = make_env(
            0, 0, "libero_10_task", max_episode_steps=200, enable_eef_control=True
        )
        facade = LiberoEnvFacade(env, meta={})

        class LocalRpc:
            def call(self, name, args=(), kwargs=None, **ignored):
                return facade._rpc[name](*args, **(kwargs or {}))

        client = LiberoEnvClient(LocalRpc(), expected_meta={})
        selected = [
            item
            for item in native_catalog()
            if item["name"] in {"finish", "rotate_axis"}
        ]
        toolkit = ManualToolkit(
            selected=selected,
            journal=RunJournal(root / "journal"),
            runtime_kwargs={"env": client, "model": None, "sam3_client": None},
            dashboard_events=SimpleNamespace(enabled=False, emit=lambda *args: None),
            memory=MemoryManager(root / "empty-memory"),
            state_output_dir=root / "state",
        )
        remember_children()
        report["selected_names"] = [tool.name for tool in toolkit.list_tools()]
        report["controller"] = client.get_eef_controller_state()

        def robot_state():
            raw = client.raw_obs()
            frame = env.env.workers[0].get_env_attr("probe_robot_frame")
            body = Rotation.from_quat(np.asarray(frame["body_quat_wxyz"])[[1, 2, 3, 0]])
            site = Rotation.from_matrix(frame["site_rotation"])
            observed = Rotation.from_quat(raw["robot0_eef_quat"])
            assert frame["controller_ref_name"] == frame["site_name"]
            assert frame["controller_ref_site_id"] == frame["site_id"]
            np.testing.assert_allclose(
                raw["robot0_eef_pos"], frame["site_position"], atol=1e-7, rtol=0
            )
            assert (observed * body.inv()).magnitude() <= 1e-7
            return {
                "eef_xyz": np.asarray(raw["robot0_eef_pos"]).tolist(),
                "eef_quat_xyzw": observed.as_quat().tolist(),
                "body_to_site_rotation": (body.inv() * site).as_matrix().tolist(),
                **frame,
            }

        first = robot_state()
        reference_offset = Rotation.from_matrix(first["body_to_site_rotation"])
        report["initial_robot_frame"] = first
        p = toolkit.primitives
        inner_step = p._step_env

        def traced_step(action):
            assert len(trace) < 160
            inner_step(action)
            state = robot_state()
            change = (
                Rotation.from_matrix(state["body_to_site_rotation"])
                * reference_offset.inv()
            ).magnitude()
            state["offset_change_rad"] = float(change)
            trace.append({"action": np.asarray(action).tolist(), **state})
            assert change <= 1e-7
            assert action[6] == 0
            np.testing.assert_array_equal(
                state["gripper_target"], first["gripper_target"]
            )

        p._step_env = traced_step
        for axis, angle in [("x", 0.08), ("x", -0.08), ("z", 0.08), ("z", -0.08)]:
            before = robot_state()
            start_index = len(trace)
            start_frames = p.recorded_frame_count()
            result = toolkit.execute_tool(
                "rotate_axis", {"axis": axis, "angle_rad": angle}
            )
            record = toolkit.state.get()
            case = {
                "axis": axis,
                "angle_rad": angle,
                "before": before,
                "recorded_step": record.step_idx,
                "result": record.result,
                "returned_images": len(result.images),
            }
            report["cases"].append(case)
            assert not result.is_error, result.data
            assert record.command["action"] == "rotate_axis"
            count = len(trace) - start_index
            assert (
                count
                == record.result["steps_used"]
                == p.recorded_frame_count() - start_frames
            )
            assert 0 < count <= 40
            after = robot_state()
            actual = (
                Rotation.from_quat(after["eef_quat_xyzw"])
                * Rotation.from_quat(before["eef_quat_xyzw"]).inv()
            ).as_rotvec()
            index = 0 if axis == "x" else 2
            case.update(
                after=after,
                actual_control_steps=count,
                actual_world_rotation_vector=actual.tolist(),
                max_position_deviation_m=max(
                    float(
                        np.linalg.norm(np.asarray(item["eef_xyz"]) - before["eef_xyz"])
                    )
                    for item in trace[start_index:]
                ),
            )
            assert actual[index] * angle > 0
            assert record.result["position_tolerance_m"] == 0.012
            assert record.result["orientation_tolerance_rad"] == 0.02
            assert record.result["position_error_m"] < 0.012
            assert record.result["orientation_error_rad"] < 0.02
            assert record.result["target_reached"]
            assert len(result.images) >= 2
            np.testing.assert_array_equal(
                record.result["target_xyz"], before["eef_xyz"]
            )
            np.testing.assert_array_equal(
                after["gripper_target"], first["gripper_target"]
            )
            for i, data in enumerate(result.images):
                (root / f"returned-{len(report['cases'])}-{i}.png").write_bytes(data)
            case["passed"] = True
        report.update(
            passed=True,
            transform_gate_passed=True,
            actual_control_steps=len(trace),
            max_body_site_offset_change_rad=max(
                item["offset_change_rad"] for item in trace
            ),
            actual_gripper_target_preserved=True,
            controller_reference_matches_observed_site=True,
        )
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        remember_children()
        if toolkit is not None:
            toolkit.close()
        if facade is not None:
            facade.close()
        elif env is not None:
            env.env.close()
        signal.alarm(0)
        report["owned_children_start_ticks"] = owned
        report["facade_closed"] = facade is not None and facade._closed
        report["private_config_unchanged"] = (
            hashlib.sha256(config.read_bytes()).hexdigest() == before_config
        )
        (root / "trace.json").write_text(json.dumps(trace, indent=2) + "\n")
        (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
