# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""CPU checks for sensor isolation and native command accounting."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from robots.univtac.backend import UniVTACBackend, save_native_frame
from robots.univtac.control import apply_native, validate_command
from robots.univtac.observations import sensor_observation


def test_sensor_allowlist_drops_privileged_native_fields():
    rgb = np.zeros((2, 3, 3), dtype=np.uint8)
    markers = np.array([[[1, 2], [3, 4]], [[2, 4], [3, 5]]])
    native = {
        "observation": {"head": {"rgb": rgb, "hidden_pose": [999]}},
        "tactile": {"left_tactile": {"rgb": rgb, "marker": markers, "pose": [999]}},
        "actor": {"hole_pose": [999]},
        "atom": {"tag": "expert-insert"},
        "success": True,
    }
    state = {
        "root_pose_w": {"position": [1, 0, 0], "quaternion_wxyz": [1, 0, 0, 0]},
        "hand_pose": {"position": [0.1, 0, 0], "quaternion_wxyz": [1, 0, 0, 0]},
        "qpos": [0] * 7 + [0.0195],
        "gripper_qpos": 0.0195,
    }
    result = sensor_observation(
        native, state, {"left": rgb}, control_step=1, physics_step=2
    )
    assert set(result) == {
        "cameras",
        "tactile",
        "state",
        "timestamp",
        "control_step",
        "physics_step",
        "physics_dt",
        "simulation_time_s",
    }
    assert set(result["cameras"]["head"]) == {
        "rgb",
        "image_size",
        "image_origin",
        "image_axes",
    }
    assert result["cameras"]["head"]["image_size"] == [2, 3]
    assert "pose" not in result["tactile"]["left"]
    assert result["tactile"]["left"]["reference_kind"] == "episode_initial_contact"
    np.testing.assert_array_equal(
        result["tactile"]["left"]["marker_displacement"], [[1, 2], [0, 1]]
    )
    assert result["state"]["eef_pose_wxyz"][0] == 1.1
    assert result["state"]["gripper"] == 0.5
    rgb[:] = 255
    assert not result["cameras"]["head"]["rgb"].any()


@pytest.mark.parametrize(
    "action",
    [
        [0] * 8,
        [0, 0, 0, 1, 0, 0, 0, 2],
        [np.nan, 0, 0, 1, 0, 0, 0, 0],
        [0] * 7,
    ],
)
def test_invalid_commands_rejected(action):
    with pytest.raises(ValueError):
        validate_command(action)


class Tensor(np.ndarray):
    def clone(self):
        return self.copy()

    def new_tensor(self, value):
        return np.asarray(value, dtype=float).view(Tensor)


class NativeTask:
    def __init__(self, *, success_on_first=False):
        self.cfg = SimpleNamespace(step_lim=300)
        self.take_action_cnt = 299
        self.step_count = 900
        self.eval_success = False
        self.plan_success = True
        self.success_on_first = success_on_first
        self.positions = np.zeros(8).view(Tensor)
        self._robot_manager = SimpleNamespace(
            robot=SimpleNamespace(data=SimpleNamespace(joint_pos=self.positions)),
            get_observations=lambda _: {"joint": self.positions},
            set_arm=self.set_arm,
            set_gripper=lambda value, **_: None,
        )

    def set_arm(self, value, **_):
        self.positions[:7] = value

    def take_action(self, value, action_type, force):
        self.take_action_cnt += 1
        self.positions[:] = value
        self._step()
        self.eval_success = self.success_on_first
        return True, self.eval_success

    def _step(self):
        self.step_count += 1

    def check_early_stop(self):
        return False

    def check_success(self):
        return self.eval_success


def test_final_native_slot_completes_two_physics_steps_without_extra_charge():
    task = NativeTask()
    receipt = apply_native(task, np.ones(8) * 0.01)
    assert receipt == {
        "exec_success": True,
        "native_action_delta": 1,
        "physics_step_delta": 2,
    }
    assert task.take_action_cnt == 300
    with pytest.raises(RuntimeError, match="termination"):
        apply_native(task, np.zeros(8))


def test_official_success_stops_inside_command():
    task = NativeTask(success_on_first=True)
    receipt = apply_native(task, np.zeros(8))
    assert receipt["physics_step_delta"] == 1
    assert "success" not in receipt
    assert "official_success" not in receipt


def test_rejected_ik_counts_toward_attempt_budget_without_native_motion():
    backend = UniVTACBackend.__new__(UniVTACBackend)
    backend.task = NativeTask()
    backend.task.take_action_cnt = 0
    backend.controller = SimpleNamespace(
        execute=lambda _: {
            "exec_success": False,
            "native_action_delta": 0,
            "physics_step_delta": 0,
        }
    )
    backend.recording_finished = False
    backend.attempted_commands = 299
    backend.observation = lambda: {"control_step": backend.task.take_action_cnt}
    result = backend.step([0, 0, 0, 1, 0, 0, 0, 0.5])
    assert result[2] is True
    assert result[4]["attempted_commands"] == 300
    assert backend.task.take_action_cnt == 0
    with pytest.raises(RuntimeError, match="Episode ended"):
        backend.step([0, 0, 0, 1, 0, 0, 0, 0.5])


def test_invalid_command_does_not_charge_attempt_budget():
    backend = UniVTACBackend.__new__(UniVTACBackend)
    backend.task = NativeTask()
    backend.controller = SimpleNamespace()
    backend.recording_finished = False
    backend.attempted_commands = 12
    with pytest.raises(ValueError):
        backend.step([0] * 8)
    assert backend.attempted_commands == 12


def test_private_archive_is_numeric_and_keeps_truth_outside_agent_frames(tmp_path):
    path = tmp_path / "evaluator-frames" / "initial.npz"
    save_native_frame(
        path,
        {
            "actor": {"hole_pose": np.arange(7)},
            "observation": {"head": {"depth": np.ones((2, 3))}},
            "atom": {"tag": "native-expert-tag"},
        },
    )
    with np.load(path, allow_pickle=False) as archive:
        np.testing.assert_array_equal(archive["actor/hole_pose"], np.arange(7))
        assert archive["atom/tag"].item() == "native-expert-tag"
    assert not path.with_suffix(".partial").exists()


def test_flush_recording_does_not_close_simulation_app():
    calls = []
    backend = UniVTACBackend.__new__(UniVTACBackend)
    backend.task = SimpleNamespace(
        video_handler=SimpleNamespace(
            ffmpeg=object(),
            close=lambda: calls.append("video"),
        )
    )
    backend.app = SimpleNamespace(close=lambda: calls.append("app"))
    assert backend.finish_recording() == {"recording_finished": True}
    assert calls == ["video"]


def smoke_reservation(tmp_path):
    from robots.univtac.pilot import Pilot

    pilot = Pilot.create(tmp_path / "pilot")
    output = tmp_path / "output"
    output.mkdir()
    attempt = pilot.reserve_episode("dev-01", str(output))
    (output / "pilot-attempt.json").write_text(
        json.dumps(
            {
                "pilot_root": str(pilot.root),
                "output_dir": str(output),
                "attempt_id": attempt,
                "cell": pilot._cell("dev-01"),
                "freeze_id": None,
            }
        )
    )
    return pilot, output


def test_script_smoke_records_scene_before_motion_and_finishes_once(tmp_path):
    from robots.univtac.smoke import run_smoke

    pilot, output = smoke_reservation(tmp_path)
    calls = []

    class Backend:
        def __init__(self, **kwargs):
            self.task = SimpleNamespace(
                play_once=lambda: calls.append("expert"),
                check_success=lambda: True,
            )

        def reset(self):
            calls.append("reset")
            return self.observation(), {}

        def observation(self):
            return {
                "state": {
                    "eef_pose_wxyz": np.array([0, 0, 0, 1, 0, 0, 0]),
                    "gripper": 0.5,
                }
            }

        def evaluator_state(self):
            return {
                "scene": {
                    key: {"fixed": 1}
                    for key in (
                        "model",
                        "state",
                        "physics",
                        "sensors",
                        "rng",
                        "assets",
                    )
                },
                "video_path": "native.mp4",
            }

        def step(self, command):
            events = [
                json.loads(line)
                for line in (pilot.root / "events.jsonl").read_text().splitlines()
            ]
            assert events[-1]["kind"] == "scene"
            calls.append("hold")
            return self.observation(), 0, False, False, {"exec_success": True}

        def finish_recording(self):
            calls.append("flush")

        def close(self):
            calls.append("close")

    outcome = run_smoke(root="unused", output_dir=output, backend_factory=Backend)
    assert outcome["official_success"] is True
    assert outcome["model_score"] is False
    assert calls[:3] == ["reset", "hold", "expert"]
    assert calls[-1] == "close"
    with pytest.raises(ValueError, match="already finished"):
        run_smoke(root="unused", output_dir=output, backend_factory=Backend)
    events = [
        json.loads(line)
        for line in (pilot.root / "events.jsonl").read_text().splitlines()
    ]
    assert sum(event["kind"] == "finished" for event in events) == 1
    assert events[-1]["maker_inputs"] == {}


def test_script_smoke_setup_failure_consumes_reserved_slot_without_retry(tmp_path):
    from robots.univtac.smoke import run_smoke

    pilot, output = smoke_reservation(tmp_path)

    def broken_backend(**kwargs):
        raise RuntimeError("missing dependency")

    result = run_smoke(root="unused", output_dir=output, backend_factory=broken_backend)
    assert result["termination_reason"] == "setup_failure"
    assert result["official_success"] is None
    events = [
        json.loads(line)
        for line in (pilot.root / "events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["kind"] == "finished"
    assert (output / "smoke-error.txt").exists()
