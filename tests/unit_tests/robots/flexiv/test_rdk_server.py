# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     https://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Direct RDK contracts with fake native hardware, never a robot connection."""

import copy
import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from robots.flexiv.rdk_server import (
    DeltaRequest,
    DirectRobot,
    GripperRequest,
    PoseRequest,
    ServerConfig,
    create_app,
    robot_owner_lock,
)


class FakeRobot:
    def __init__(self):
        self.calls = []
        self.pose = [0.4, 0, 0.2, 1, 0, 0, 0]
        self.target = None
        self.progress = 0
        self.arrival_after = 15
        self.current_mode = "cartesian"
        self.bad = False
        self.on_send = None

    def states(self):
        if self.target is not None:
            self.progress += 1
            if self.progress >= self.arrival_after:
                self.pose = self.target[:]
                self.target = None
        return SimpleNamespace(
            tcp_pose=self.pose[:],
            q=[0.0] * 7,
            dq=[0.01 if self.target else 0.0] * 7,
            tcp_vel=[0.0] * 6,
            ext_wrench_in_world=[1.0] * 6,
            ext_wrench_in_tcp=[2.0] * 6,
        )

    def connected(self):
        return True

    def fault(self):
        return self.bad

    def operational(self):
        return True

    def mode(self):
        return self.current_mode

    def Enable(self):
        self.calls.append(("enable",))

    def SwitchMode(self, mode):
        self.calls.append(("mode", mode))
        self.current_mode = mode

    def Stop(self):
        self.calls.append(("stop",))
        self.target = None
        self.current_mode = "idle"

    def SendCartesianMotionForce(self, target, **kwargs):
        self.calls.append(("pose", target[:], kwargs))
        self.target = target[:]
        if self.on_send:
            self.on_send()


class FakeGripper:
    def __init__(self, robot):
        self.robot = robot
        self.width = 0.08
        self.target = None
        self.name = "Flexiv-GN01"
        self.progress = 0
        self.contact = False

    def params(self):
        return SimpleNamespace(
            name=self.name,
            min_width=0.0,
            max_width=0.098,
            min_vel=0.01,
            max_vel=0.1,
            min_force=1,
            max_force=40,
        )

    def states(self):
        moving = self.target is not None
        if moving:
            self.progress += 1
            if self.progress >= 5:
                self.width = 0.03 if self.contact else self.target
                self.target = None
                moving = False
        return SimpleNamespace(
            width=self.width, force=-12 if self.contact else 0.0, is_moving=moving
        )

    def Enable(self, name):
        self.robot.calls.append(("gripper_enable", name))
        self.name = name

    def Move(self, width, velocity, force):
        self.robot.calls.append(("gripper_move", width, velocity, force))
        self.target = width

    def Stop(self):
        self.robot.calls.append(("gripper_stop",))
        self.target = None


class FakeTool:
    def __init__(self, robot):
        pass

    def name(self):
        return "Flexiv-GN01"

    def params(self):
        return SimpleNamespace(tcp_location=[0, 0, 0.19, 1, 0, 0, 0])


@pytest.fixture
def direct(monkeypatch, tmp_path):
    now = [0.0]
    monkeypatch.setattr("robots.flexiv.rdk_server.time.monotonic", lambda: now[0])
    monkeypatch.setattr(
        "robots.flexiv.rdk_server.time.sleep", lambda s: now.__setitem__(0, now[0] + s)
    )
    config = ServerConfig(
        robot_sn="fake",
        workspace_min=[0, -0.8, -0.49],
        workspace_max=[1, 0.8, 1],
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    rdk = SimpleNamespace(
        Tool=FakeTool,
        Gripper=FakeGripper,
        Mode=SimpleNamespace(NRT_CARTESIAN_MOTION_FORCE="cartesian"),
    )
    robot = FakeRobot()
    controller = DirectRobot(config, rdk=rdk, robot=robot)
    return controller


def test_startup_reads_without_enabling_or_moving(direct):
    state = direct.state()
    assert not state["armed"] and not state["gripper_ready"]
    assert direct.robot.calls == []
    assert state["tool"] == {
        "name": "Flexiv-GN01",
        "tcp_location": [0, 0, 0.19, 1, 0, 0, 0],
    }
    assert state["state"]["ext_wrench_in_tcp"] == [2.0] * 6
    assert "audit_path" not in state["config"]


def test_one_native_target_continues_beyond_old_200ms(direct):
    direct.enable()
    result = direct.move(PoseRequest(position_m=[0.45, 0, 0.2]))
    assert result["reached"]
    assert result["elapsed_s"] > 0.2
    np.testing.assert_allclose(result["measured_pose"][:3], [0.45, 0, 0.2])
    commands = [call for call in direct.robot.calls if call[0] == "pose"]
    assert len(commands) == 1
    assert not any(call[0] == "stop" for call in direct.robot.calls)
    records = [json.loads(line) for line in open(direct.config.audit_path)]
    assert records[-1]["event"] == "result"
    assert any(row["event"] == "state" for row in records)


def test_delta_is_base_frame_and_resolved_once(direct):
    direct.enable()
    direct.robot.pose[3:] = [np.sqrt(0.5), 0, 0, np.sqrt(0.5)]
    result = direct.move(
        DeltaRequest(translation_m=[0.02, 0, 0], rotation_vector_rad=[0.1, 0, 0])
    )
    np.testing.assert_allclose(result["target_pose"][:3], [0.42, 0, 0.2])
    from scipy.spatial.transform import Rotation

    expected = Rotation.from_rotvec([0.1, 0, 0]) * Rotation.from_euler(
        "z", 90, degrees=True
    )
    np.testing.assert_allclose(
        result["target_pose"][3:], np.roll(expected.as_quat(), 1), atol=1e-12
    )


@pytest.mark.parametrize(
    "command",
    [
        PoseRequest(position_m=[0.6, 0, 0.2]),
        PoseRequest(position_m=[0.4, 0, 0.2], quaternion_wxyz=[0, 0, 0, 0]),
        DeltaRequest(translation_m=[0, 0, 0], rotation_vector_rad=[2 * np.pi, 0, 0]),
    ],
)
def test_bad_arguments_do_not_move_or_disarm(direct, command):
    direct.enable()
    before = copy.deepcopy(direct.robot.calls)
    with pytest.raises(ValueError):
        direct.move(command)
    assert direct.armed
    assert direct.robot.calls == before


def test_timeout_stops_native_motion(direct):
    direct.enable()
    direct.config.timeout_s = 0.1
    direct.robot.arrival_after = 10000
    with pytest.raises(TimeoutError):
        direct.move(PoseRequest(position_m=[0.45, 0, 0.2]))
    assert not direct.armed
    assert direct.robot.calls[-2:] == [("stop",), ("gripper_stop",)]


def test_hardware_fault_during_execution_stops(direct):
    direct.enable()
    direct.robot.on_send = lambda: setattr(direct.robot, "bad", True)
    with pytest.raises(HTTPException, match="hardware fault"):
        direct.move(PoseRequest(position_m=[0.45, 0, 0.2]))
    assert not direct.armed
    assert direct.robot.target is None


def test_stop_between_validation_and_send_prevents_dispatch(direct, monkeypatch):
    direct.enable()
    original = direct._target

    def stop_before_send(*args):
        target = original(*args)
        direct.stop("race test")
        return target

    monkeypatch.setattr(direct, "_target", stop_before_send)
    with pytest.raises(HTTPException, match="cancelled"):
        direct.move(PoseRequest(position_m=[0.45, 0, 0.2]))
    assert not any(call[0] == "pose" for call in direct.robot.calls)
    assert direct.stop_reason == "race test"


def test_stop_interrupts_wait_without_waiting_for_command_lock(direct, monkeypatch):
    direct.enable()
    dispatched = threading.Event()
    continue_worker = threading.Event()
    errors = []
    direct.robot.on_send = dispatched.set

    def wait(_):
        assert continue_worker.wait(2)

    monkeypatch.setattr("robots.flexiv.rdk_server.time.sleep", wait)

    def move():
        try:
            direct.move(PoseRequest(position_m=[0.45, 0, 0.2]))
        except HTTPException as exc:
            errors.append(exc)

    worker = threading.Thread(target=move)
    worker.start()
    assert dispatched.wait(2)
    with pytest.raises(HTTPException, match="Another robot command"):
        direct.move(DeltaRequest(translation_m=[0.01, 0, 0]))
    direct.stop()
    count = len(direct.robot.calls)
    continue_worker.set()
    worker.join(2)
    assert not worker.is_alive()
    assert errors and len(direct.robot.calls) == count


@pytest.mark.parametrize("contact", [False, True])
def test_gripper_is_one_native_move_without_2mm_steps(direct, contact):
    direct.enable()
    direct.gripper.contact = contact
    result = direct.move_gripper(GripperRequest(width_m=0.02))
    commands = [call for call in direct.robot.calls if call[0] == "gripper_move"]
    assert commands == [("gripper_move", 0.02, 0.02, 20)]
    assert result["reached"] is not contact
    assert result["reason"] == (
        "stationary_before_target" if contact else "target_reached"
    )
    assert result["force_n"] == (-12 if contact else 0)
    assert (
        ("gripper_stop",) in direct.robot.calls
        if contact
        else ("gripper_stop",) not in direct.robot.calls
    )
    assert direct.armed


@pytest.mark.parametrize("force", [-20.0, 0.0])
def test_gripper_stationary_short_target_stops_gripper_without_arm_stop(
    direct, monkeypatch, force
):
    direct.enable()
    monkeypatch.setattr(
        direct.gripper,
        "states",
        lambda: SimpleNamespace(width=0.03, force=force, is_moving=False),
    )
    result = direct.move_gripper(GripperRequest(width_m=0.01))
    assert result["reached"] is False
    assert result["stopped_short"] is True
    assert result["reason"] == "stationary_before_target"
    assert result["force_n"] == force
    assert result["elapsed_s"] >= 0.5
    assert direct.armed
    assert [call for call in direct.robot.calls if call[0] == "gripper_move"] == [
        ("gripper_move", 0.01, 0.02, 20)
    ]
    assert direct.robot.calls[-1] == ("gripper_stop",)
    assert ("stop",) not in direct.robot.calls


def test_http_validation_and_stop_routes(direct):
    with TestClient(create_app(direct)) as client:
        assert client.get("/health").json()["service"] == "flexiv-rdk"
        assert client.post("/enable").status_code == 200
        assert client.post("/delta", json={"translation_m": [1, 2]}).status_code == 422
        assert (
            client.post("/delta", json={"translation_m": [0.2, 0, 0]}).status_code
            == 422
        )
        assert client.get("/state").json()["armed"]
        assert client.post("/stop").json()["stopped"]
        assert (
            client.post("/pose", json={"position_m": [0.41, 0, 0.2]}).status_code == 409
        )


def test_no_automatic_gripper_initialization(direct):
    direct.activate_gripper()
    direct.enable()
    assert not any(call[0] == "gripper_enable" for call in direct.robot.calls)
    assert direct.gripper is not None


def test_second_server_owner_is_rejected_before_connection():
    with robot_owner_lock("Fake-Robot-Test-Only"):
        with pytest.raises(RuntimeError, match="Another direct RDK server"):
            with robot_owner_lock("Fake-Robot-Test-Only"):
                pytest.fail("Second server acquired the robot")
    with robot_owner_lock("Fake-Robot-Test-Only"):
        pass
