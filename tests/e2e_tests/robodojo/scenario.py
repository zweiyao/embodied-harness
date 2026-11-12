# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""RoboDojo phases reuse the public runtime and scripted CLI helpers."""

from __future__ import annotations

import threading
import time
from functools import cached_property
from pathlib import Path

from robots.robodojo.robot_spec import get_robot_spec
from robots.robodojo.toolkit import RoboDojoToolkit
from rpent.dashboard.events import NullDashboardEventSink
from rpent.memory import MemoryManager
from rpent.robots.components.pi05_vla_client import _encode_obs_robodojo
from rpent.utils import logging
from tests.e2e_tests.common import (
    ScriptedToolCall,
    array_summary,
    parse_runtime_args,
    prepare_suite,
    require_array,
    require_depth,
    require_rgb,
    run_scripted_policy_chain,
    runtime_phase,
    selected_cuda_ordinal,
)


class RoboDojoScenario:
    def __init__(self, output_dir: Path):
        self.output = prepare_suite(
            output_dir=output_dir,
            stack="robodojo",
            extra="robodojo",
            details={
                "environment_setup": "prepared; dependency consistency is recorded separately",
                "task": "put_bottles_into_dustbin",
                "layout": 0,
            },
        )
        self.spec = get_robot_spec()
        self.argv = [
            "--task",
            "put_bottles_into_dustbin",
            "--layout",
            "0",
            "--max-episode-steps",
            "64",
            "--cuda-device",
            str(selected_cuda_ordinal()),
        ]
        self.args = parse_runtime_args(self.spec, self.argv)

    @cached_property
    def environment(self):
        with runtime_phase(
            self.spec, self.args, self.output / "environment", {"env"}
        ) as runtime:
            env = runtime["env"]
            obs = env.get_obs()
            assert env.get_status()["step"] == 0
            assert obs["instruction"].strip()
            encoded = _encode_obs_robodojo(obs)
            require_array(encoded["states"], "state", ndim=2, last_dim=14)
            cameras = {}
            for name in ("cam_head", "cam_left_wrist", "cam_right_wrist"):
                cam = obs["vision"][name]
                rgb = require_rgb(cam["color"], name)
                depth = require_depth(
                    cam.get("distance_to_image_plane", cam.get("depth")),
                    name + ".depth",
                    rgb,
                )
                meta = env.get_camera_meta(name)
                require_array(meta["intrinsic_matrix"], name + ".K", ndim=2, last_dim=3)
                require_array(meta["extrinsic_matrix"], name + ".T", ndim=2, last_dim=4)
                cameras[name] = {
                    "rgb": array_summary(rgb),
                    "depth": array_summary(depth),
                }
            env.step(encoded["states"][0])
            assert env.get_status()["step"] == 1
            return obs, {
                "status": "passed",
                "instruction": obs["instruction"],
                "cameras": cameras,
                "native_hold_actions": 1,
            }

    @cached_property
    def pi05(self):
        observation, _ = self.environment
        with runtime_phase(
            self.spec, self.args, self.output / "pi05", {"vla"}
        ) as runtime:
            actions = require_array(
                runtime["vla_client"].predict(observation), "Pi0.5", ndim=2, last_dim=14
            )
            assert actions.shape == (50, 14)
            return {"status": "passed", "actions": array_summary(actions)}

    @cached_property
    def sam3(self):
        observation, _ = self.environment
        with runtime_phase(
            self.spec, self.args, self.output / "sam3", {"sam3"}
        ) as runtime:
            result = runtime["sam3_client"].segment(
                observation["vision"]["cam_head"]["color"], text_prompt="bottle"
            )
            assert isinstance(result.found, bool)
            if result.found:
                assert (
                    result.mask.shape
                    == observation["vision"]["cam_head"]["color"].shape[:2]
                )
            return {"status": "passed", "found": result.found, "score": result.score}

    @cached_property
    def policy_chain(self):
        return run_scripted_policy_chain(
            robot="robodojo",
            robot_argv=self.argv,
            output_dir=self.output / "policy-chain",
            action=ScriptedToolCall("pi0_pick", {"max_chunks": 1}),
            action_count_field="simulator_steps",
        )

    @cached_property
    def cancellation(self):
        output = self.output / "cancellation"
        output.mkdir()
        logging.init_output_dir(output)
        with runtime_phase(self.spec, self.args, output, {"env", "vla"}) as runtime:
            toolkit = RoboDojoToolkit(
                primitives_kwargs={**runtime, "owns_env": False},
                dashboard_events=NullDashboardEventSink(),
                memory=MemoryManager(output / "memory"),
            )
            results = []
            worker = threading.Thread(
                target=lambda: results.append(
                    toolkit.execute_tool("pi0_pick", {"max_chunks": 1})
                ),
                daemon=True,
            )
            worker.start()
            try:
                deadline = time.monotonic() + 45
                while runtime["env"].get_status()["step"] == 0:
                    assert worker.is_alive() and time.monotonic() < deadline, (
                        "Action did not start"
                    )
                    time.sleep(0.05)
                started = time.monotonic()
                toolkit.cancel_active_and_wait()
                worker.join(timeout=10)
                assert not worker.is_alive()
                steps = runtime["env"].get_status()["step"]
                time.sleep(0.2)
                assert runtime["env"].get_status()["step"] == steps
                assert 0 < steps < 50
                assert len(results) == 1 and results[0].is_error
                return {
                    "status": "passed",
                    "native_steps_before_cancelled_stop": steps,
                    "cancel_seconds": time.monotonic() - started,
                }
            finally:
                toolkit.close()
