# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""25 Hz segment, hold, rejection and interruption tests; fake hardware only."""

import copy
import importlib
import threading

import numpy as np
import pytest
from fastapi import HTTPException
from test_native_motion import target

pytest_plugins = ["test_native_motion"]


@pytest.fixture
def chunks(motion, monkeypatch):
    module = importlib.import_module("tested_native_collector.eef_chunk")
    now = [100.0]
    motion.state["gripper_force_n"] = 0.0
    motion.robot.get_live_state = lambda: copy.deepcopy(motion.state)
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        now[0] += seconds
        for camera in motion.bridge.collector.camera_mgr.cameras.values():
            camera._capture_slot._timestamp.value = now[0]

    monkeypatch.setattr(module.time, "sleep", sleep)
    controller = module.EEFChunks(motion)
    motion.eef_chunks = controller
    controller.now, controller.sleep = now, sleep
    return controller


@pytest.mark.parametrize("steps", [1, 5])
def test_fixed_goal_for_n_ticks_then_hold_without_waiting_for_goal(
    chunks, motion, steps
):
    goal = target(motion, 0.01, 0.0)
    result = chunks.execute("owner", goal, steps)
    assert result["held"] is True and result["reached"] is False
    assert result["executed_steps"] == steps and len(result["ticks"]) == steps
    assert result["segment_elapsed_s"] == pytest.approx(0.04 * steps)
    assert result["hold_elapsed_s"] == pytest.approx(0.04)
    assert len(motion.sent) == steps + 1
    for pose, limits in motion.sent[:steps]:
        np.testing.assert_allclose(pose, goal)
        assert limits["max_linear_vel"] == 0.02
    np.testing.assert_allclose(motion.sent[-1][0], motion.state["tcp_pose"])
    assert motion.armed and motion.expires == 200.0
    assert motion.stopped == [] and motion.pending_pose is None
    assert motion.command_deadline == 0.0
    assert not chunks.active
    # A second episode decision uses a fresh segment, no rearming.
    again = chunks.execute("owner", goal, 1)
    assert again["held"] and motion.armed


@pytest.mark.parametrize(
    "failure", ["steps", "bool", "quaternion", "range", "workspace"]
)
def test_pre_execution_rejections_keep_authorization(chunks, motion, failure):
    goal, steps = target(motion, 0.01, 0.0), 1
    if failure == "steps":
        steps = 6
    if failure == "bool":
        steps = True
    if failure == "quaternion":
        goal[3:] = 0.0
    if failure == "range":
        goal[0] += 0.1
    if failure == "workspace":
        goal[2] = -0.5
    with pytest.raises(HTTPException) as error:
        chunks.execute("owner", goal, steps)
    assert error.value.detail["no_execution"] is True
    assert error.value.detail["retryable"] is True
    assert motion.sent == [] and motion.stopped == [] and motion.armed
    assert motion.pending_pose is None and not chunks.active


@pytest.mark.parametrize(
    "failure",
    [
        "force",
        "state",
        "send",
        "overrun",
        "hold_timeout",
        "hold_drift",
        "joint_jump",
        "lease",
    ],
)
def test_execution_fault_stops_without_replaying(chunks, motion, monkeypatch, failure):
    original_sleep = chunks.sleep

    def sleep(seconds):
        original_sleep(seconds)
        if failure == "overrun":
            original_sleep(0.06)
        if failure == "force":
            motion.state["gripper_force_n"] = 23.0
        if failure == "joint_jump":
            motion.state["joint_position"][0] += 0.06
        if failure == "lease":
            motion.bridge.active = False
        if failure == "state":
            motion.state["tcp_pose"][0] = float("nan")
        if failure == "hold_timeout" and len(motion.sent) > 1:
            motion.state["joint_velocity"][0] = 0.006
        if failure == "hold_drift" and len(motion.sent) > 1:
            motion.state["tcp_pose"][0] += 0.006

    monkeypatch.setattr(chunks.motion.module.time, "sleep", sleep)
    if failure == "send":

        def failed(*args, **kw):
            raise RuntimeError("uncertain SDK acknowledgement")

        motion.robot._robot.SendCartesianMotionForce = failed
    with pytest.raises((RuntimeError, HTTPException)):
        chunks.execute("owner", target(motion, 0.01, 0.0), 1)
    assert not motion.armed and motion.stopped == ["robot", "gripper"]
    assert motion.pending_pose is None and not chunks.active
    assert len(motion.sent) <= 2


def test_stop_cancels_before_next_send_or_hold(chunks, motion, monkeypatch):
    def stop_during_tick(seconds):
        chunks.sleep(seconds)
        motion.halt("onsite operator stop")

    monkeypatch.setattr(motion.module.time, "sleep", stop_during_tick)
    with pytest.raises(RuntimeError, match="interrupted"):
        chunks.execute("owner", target(motion, 0.01, 0.0), 5)
    assert len(motion.sent) == 1
    assert not motion.armed and motion.stopped == ["robot", "gripper"]


def test_other_commands_block_and_feedback_cannot_clear_active_deadline(chunks, motion):
    chunks._owner_thread = -1  # another worker owns an active segment
    motion.pending_pose = np.array(motion.state["tcp_pose"])
    motion.command_deadline = 104.0
    with pytest.raises(HTTPException, match="owns the arm"):
        motion.pose_step("owner", target(motion, 0.001, 0.0), native=True)
    motion.feedback("owner")
    assert motion.command_deadline == 104.0 and motion.pending_pose is not None
    chunks._owner_thread = None


def test_cancel_serializes_against_command_send(chunks, motion):
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()

    def slow_send(*args, **kw):
        entered.set()
        assert release.wait(2.0)

    motion.robot._robot.SendCartesianMotionForce = slow_send
    sender = threading.Thread(
        target=chunks._send, args=(motion.robot, motion.state["tcp_pose"], 0)
    )
    sender.start()
    assert entered.wait(2.0)

    def cancel():
        motion.halt("operator stop")
        stopped.set()

    stopper = threading.Thread(target=cancel)
    stopper.start()
    assert not stopped.wait(0.02)
    release.set()
    sender.join(2.0)
    stopper.join(2.0)
    assert stopped.is_set() and not motion.armed
    with pytest.raises(RuntimeError, match="interrupted"):
        chunks._send(motion.robot, motion.state["tcp_pose"], 0)


def test_tick_poses_and_remaining_error_are_measured(chunks, motion, monkeypatch):
    def advance(seconds):
        chunks.sleep(seconds)
        if len(motion.sent) <= 3:
            motion.state["tcp_pose"][0] += 0.0001

    monkeypatch.setattr(motion.module.time, "sleep", advance)
    result = chunks.execute("owner", target(motion, 0.01, 0.0), 3)
    assert [tick["state"]["tcp_pose"][0] for tick in result["ticks"]] == pytest.approx(
        [0.4001, 0.4002, 0.4003]
    )
    assert result["translation_error_m"] == pytest.approx(0.0097)
    assert result["held"] and not result["reached"]
    np.testing.assert_allclose(motion.sent[-1][0][:3], [0.4003, 0, 0.2])


def test_initial_bad_force_halts_without_sending(chunks, motion):
    motion.state["gripper_force_n"] = 23.0
    with pytest.raises(RuntimeError, match="feedback"):
        chunks.execute("owner", target(motion, 0.01, 0.0), 1)
    assert motion.sent == [] and not motion.armed


def test_stale_cameras_stop_during_segment(chunks, motion, monkeypatch):
    monkeypatch.setattr(
        motion.module.time,
        "sleep",
        lambda seconds: chunks.now.__setitem__(0, chunks.now[0] + seconds),
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        chunks.execute("owner", target(motion, 0.01, 0.0), 5)
    assert not motion.armed and len(motion.sent) <= 4


def test_eef_http_route_executes_in_worker(chunks, motion, monkeypatch):
    import asyncio
    import sys
    from types import ModuleType, SimpleNamespace

    from starlette.requests import Request

    fake_home = ModuleType("tested_native_collector.joint_home")
    fake_home.JointHome = lambda m: SimpleNamespace(owner=None, pending=None)
    monkeypatch.setitem(sys.modules, fake_home.__name__, fake_home)
    installed = motion.module.install_supervised_motion(motion.bridge)
    installed.armed, installed.expires, installed.owner = True, 200.0, "owner"
    threads = []
    original = motion.robot._robot.SendCartesianMotionForce

    def send(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)

    motion.robot._robot.SendCartesianMotionForce = send
    endpoint = next(
        route.endpoint
        for route in motion.bridge.collector.app.routes
        if route.path == "/rpent/supervised/eef-chunk"
    )
    schema = importlib.import_module("tested_native_collector.eef_chunk").EEFChunk
    command = schema(pose=target(motion, 0.01, 0.0).tolist(), steps=1)
    request = Request({"type": "http", "headers": [(b"x-rpent-session", b"owner")]})
    caller = threading.get_ident()
    result = asyncio.run(endpoint(command, request))
    assert result["held"] and installed.armed
    assert threads and all(thread != caller for thread in threads)
    assert installed.command_deadline == 0.0


def test_already_at_target_is_valid_json_and_keeps_hold(chunks, motion):
    import json

    result = chunks.execute("owner", motion.state["tcp_pose"], 1)
    assert result["reached"] is True
    assert json.loads(json.dumps(result, allow_nan=False))["held"] is True
    assert motion.armed
