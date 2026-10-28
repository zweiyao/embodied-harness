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

"""Offline action contracts with fake measured feedback, never hardware."""

import copy
from types import SimpleNamespace

import numpy as np
import pytest

from robots.flexiv.env_server import CollectorBackend, FlexivEnvFacade
from robots.flexiv.motion import rotation


@pytest.fixture
def backend(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("robots.flexiv.motion.time.monotonic", lambda: now[0])
    monkeypatch.setattr(
        "robots.flexiv.motion.time.sleep", lambda s: now.__setitem__(0, now[0] + s)
    )
    b = CollectorBackend("unused", supervised=True)
    b.session = "owned"
    b.connection = {
        "motion_enabled": True,
        "workspace_min": [0, -0.8, -0.49],
        "workspace_max": [1, 0.8, 1],
    }
    b.calibration = SimpleNamespace(
        data={"T_base_board": np.eye(4).tolist()}, offset=np.array([0, 0, 0.00837])
    )
    state = {
        "tcp_pose": [0.4, 0, 0.2, 0, 1, 0, 0],
        "joint_velocity": [0.0] * 7,
        "gripper_width_m": 0.098,
        "gripper_force_n": 0.0,
        "gripper_is_moving": False,
        "fault": False,
        "operational": True,
        "mode": "Mode.NRT_CARTESIAN_MOTION_FORCE",
    }
    b.calls = []
    b.state = state
    b.armed = True

    def request(path, data=None):
        b.calls.append((path, data))
        if path.endswith("/state"):
            return {
                "state": copy.deepcopy(state),
                "armed": b.armed,
                "stop_reason": None,
            }
        if path.endswith("/pose-target"):
            state["tcp_pose"] = list(data["pose"])
        if path.endswith("/gripper-step"):
            state["gripper_width_m"] = data["width_m"]
        if path.endswith("/stop"):
            b.armed = False
        return {"submitted": True}

    b.request = request
    return b


def test_motion_is_bounded_and_returns_actual_feedback(backend):
    result = backend.move_tcp([0.402, 0, 0.2])
    assert result["reached"] and result["commands"] == 1
    np.testing.assert_allclose(result["measured_pose"][:3], [0.402, 0.0, 0.2])
    sent = [data for path, data in backend.calls if path.endswith("/pose-target")]
    assert len(sent) == 1
    np.testing.assert_allclose(sent[0]["pose"][:3], [0.402, 0.0, 0.2])


@pytest.mark.parametrize("failure", [None, "stop", "timeout"])
def test_joint_home_waits_for_feedback_and_stops_on_failure(backend, failure):
    original = backend.request
    count = [0]
    backend.state["joint_position"] = [0.0] * 7

    def request(path, data=None):
        if path.endswith("home-step"):
            count[0] += 1
            if count[0] == 2:
                return {"reached": True, "joint_error_rad": 0.0}
            if failure != "timeout":
                backend.state["joint_position"] = [0.001] * 7
            if failure == "stop":
                backend.armed = False
            return {"reached": False, "target_joints_rad": [0.001] * 7}
        return original(path, data)

    backend.request = request
    if failure:
        with pytest.raises(RuntimeError):
            backend.reset_home()
        assert count[0] == 1
        assert backend.calls[-1][0].endswith("/stop")
    else:
        assert backend.reset_home()["reached"]
        assert count[0] == 2


@pytest.mark.parametrize(
    "target", [[float("nan"), 0, 0.2], [0.8, 0, 0.2], [0.4, 0, -0.49]]
)
def test_invalid_target_sends_no_commands(backend, target):
    with pytest.raises(ValueError):
        backend.move_tcp(target)
    assert all(path.endswith("/state") for path, _ in backend.calls)


def test_operator_stop_prevents_following_actions(backend):
    backend.stop_motion()
    with pytest.raises(RuntimeError, match="operator"):
        backend.move_tcp([0.401, 0, 0.2])
    assert not any(path.endswith("/pose-target") for path, _ in backend.calls)


def test_timeout_stops_and_never_accumulates_targets(backend):
    request = backend.request

    def frozen(path, data=None):
        if path.endswith("/pose-target"):
            backend.calls.append((path, data))
            return {"submitted": True}
        return request(path, data)

    backend.request = frozen
    with pytest.raises(RuntimeError, match="did not settle"):
        backend.move_tcp([0.402, 0, 0.2])
    assert sum(p.endswith("/pose-target") for p, _ in backend.calls) == 1
    assert backend.calls[-1][0].endswith("/stop")


def test_contact_holds_without_more_closure_or_claiming_grasp(backend):
    request = backend.request

    def contact(path, data=None):
        result = request(path, data)
        if path.endswith("/gripper-step"):
            backend.state["gripper_force_n"] = 5.5
        return result

    backend.request = contact
    result = backend.set_gripper(0.04)
    assert (
        result["contact_detected"]
        and not result["object_grasp_verified"]
        and not result["reached"]
    )
    assert sum(p.endswith("/gripper-step") for p, _ in backend.calls) == 1
    assert any(p.endswith("/gripper-hold") for p, _ in backend.calls)


def test_gripper_wrong_direction_stops(backend):
    request = backend.request
    backend.state["gripper_width_m"] = 0.05

    def wrong(path, data=None):
        result = request(path, data)
        if path.endswith("/gripper-step"):
            backend.state["gripper_width_m"] = 0.051
        return result

    backend.request = wrong
    with pytest.raises(RuntimeError, match="direction"):
        backend.set_gripper(0.04)
    assert backend.calls[-1][0].endswith("/stop")


def test_table_down_uses_calibration_and_checks_clearance(backend):
    board = np.eye(4)
    from scipy.spatial.transform import Rotation

    board[:3, :3] = Rotation.from_euler("x", 5, degrees=True).as_matrix()
    backend.calibration.data["T_base_board"] = board.tolist()
    pose = backend.align_tool_down()["measured_pose"]
    np.testing.assert_allclose(
        rotation(pose).as_matrix()[:, 2], -board[:3, 2], atol=1e-8
    )
    backend.state["tcp_pose"][2] = 0.02
    with pytest.raises(ValueError, match="Raise"):
        backend.align_tool_down()


def test_supervised_rpc_exposes_actions_but_never_arm(backend):
    routes = FlexivEnvFacade(backend)._rpc
    assert "env.move_tcp" in routes and "env.set_gripper" in routes
    assert all("arm" not in name and "resume" not in name for name in routes)
    backend.connection["motion_enabled"] = False
    with pytest.raises(RuntimeError, match="observation-only"):
        backend.set_gripper(0.04)


def test_gripper_waits_for_delayed_feedback_without_resending(backend):
    request = backend.request
    pending = []
    reads = [0]

    def delayed(path, data=None):
        if path.endswith("/gripper-step"):
            backend.calls.append((path, data))
            pending.append(data["width_m"])
            return {"submitted": True}
        if path.endswith("/state") and pending:
            reads[0] += 1
            if reads[0] >= 12:
                backend.state["gripper_width_m"] = pending[0]
        return request(path, data)

    backend.request = delayed
    result = backend.set_gripper(0.096)
    assert result["reached"]
    assert sum(p.endswith("/gripper-step") for p, _ in backend.calls) == 1
    assert reads[0] >= 12


def test_post_motion_capture_retries_only_transient_stationarity(backend):
    count = [0]

    def capture(path, data=None):
        count[0] += 1
        if count[0] < 3:
            raise RuntimeError(
                'Collector 409: {"detail":"Arm must be stationary; release SpaceMouse and wait"}'
            )
        return {"valid": True}

    backend.request = capture
    assert backend.calibration_snapshot() == {"valid": True}
    assert count[0] == 3

    def fault(path, data=None):
        count[0] += 1
        raise RuntimeError('Collector 409: {"detail":"Robot reports a fault"}')

    backend.request = fault
    with pytest.raises(RuntimeError, match="fault"):
        backend.calibration_snapshot()
    assert count[0] == 4


@pytest.mark.parametrize("failure", [False, True])
def test_native_home_polls_and_propagates_failure(backend, failure):
    original = backend.request
    polls = []

    def request(path, data=None):
        if path.endswith("home-step"):
            polls.append(path)
            if len(polls) == 4:
                if failure:
                    raise RuntimeError("Collector stopped: primitive deadline expired")
                return {"reached": True, "gripper_commanded": False}
            return {"reached": False, "motion": "MoveJ"}
        return original(path, data)

    backend.request = request
    if failure:
        with pytest.raises(RuntimeError, match="deadline"):
            backend.reset_home()
        assert backend.calls[-1][0].endswith("/stop")
    else:
        assert backend.reset_home()["reached"]
    assert len(polls) == 4


def test_full_five_cm_uses_one_native_target(backend):
    result = backend.move_tcp([0.45, 0, 0.2])
    assert result["commands"] == 1
    assert sum(p.endswith("/pose-target") for p, _ in backend.calls) == 1


def test_alignment_handles_more_than_ten_degrees_without_model_waypoints(backend):
    board = np.eye(4)
    from scipy.spatial.transform import Rotation

    board[:3, :3] = Rotation.from_euler("x", 30, degrees=True).as_matrix()
    backend.calibration.data["T_base_board"] = board.tolist()
    backend.state["gripper_width_m"] = 0.04
    result = backend.align_tool_down()
    assert result["reached"] and result["commands"] == 4
    np.testing.assert_allclose(
        rotation(result["measured_pose"]).as_matrix()[:, 2], -board[:3, 2], atol=1e-8
    )


def test_held_object_rotation_uses_clearance_not_gripper_opening(backend):
    from scipy.spatial.transform import Rotation

    backend.state["gripper_width_m"] = 0.04
    q = (
        Rotation.from_euler("z", 1, degrees=True) * rotation(backend.state["tcp_pose"])
    ).as_quat()
    assert backend.move_tcp([0.4, 0, 0.2], [q[3], *q[:3]])["reached"]


def test_target_below_table_is_rejected_before_sending(backend):
    backend.state["tcp_pose"][2] = 0.02
    with pytest.raises(ValueError, match="table clearance"):
        backend.move_tcp([0.4, 0, -0.01])
    assert not any(p.endswith("/pose-target") for p, _ in backend.calls)


def test_rotation_and_descent_checks_target_clearance(backend):
    from scipy.spatial.transform import Rotation

    backend.state["tcp_pose"][2] = 0.08
    q = (
        Rotation.from_euler("z", 1, degrees=True) * rotation(backend.state["tcp_pose"])
    ).as_quat()
    with pytest.raises(ValueError, match="along the motion"):
        backend.move_tcp([0.4, 0, 0.04], [q[3], *q[:3]])
    assert not any(p.endswith("/pose-target") for p, _ in backend.calls)


def test_native_target_waits_for_delayed_feedback_without_resubmission(backend):
    original = backend.request
    pending, polls = [], []

    def request(path, data=None):
        if path.endswith("/pose-target"):
            backend.calls.append((path, data))
            pending.append(data["pose"])
            return {"submitted": True}
        if path.endswith("/state") and pending:
            polls.append(path)
            if len(polls) >= 5:
                backend.state["tcp_pose"] = pending[0]
        return original(path, data)

    backend.request = request
    assert backend.move_tcp([0.45, 0, 0.2])["reached"]
    assert len(pending) == 1 and len(polls) == 6


def test_table_normal_does_not_flip_when_feedback_crosses_plane(backend):
    normal, _ = backend.table_geometry(backend.state)
    backend.state["tcp_pose"][2] = -0.01
    later, height = backend.table_geometry(backend.state)
    np.testing.assert_allclose(later, normal)
    assert height < 0


def test_stop_rpc_interrupts_a_running_motion_without_unlocking_other_moves(backend):
    import threading

    entered, stopped, released, second = [threading.Event() for _ in range(4)]

    def moving(*args):
        entered.set()
        assert released.wait(2)
        return {"stopped": True}

    def stop():
        stopped.set()
        return {"stopped": True}

    backend.move_tcp = moving
    backend.stop_motion = stop
    backend.set_gripper = lambda: second.set()
    facade = FlexivEnvFacade(backend)
    worker = threading.Thread(target=lambda: facade._dispatch("env.move_tcp", (), {}))
    queued = threading.Thread(
        target=lambda: facade._dispatch("env.set_gripper", (), {})
    )
    worker.start()
    try:
        assert entered.wait(1)
        queued.start()
        assert not second.wait(0.05)
        assert facade._dispatch("env.stop_motion", (), {})["stopped"]
        assert stopped.is_set() and not second.wait(0.05)
    finally:
        released.set()
        worker.join(2)
        if queued.ident:
            queued.join(2)
    assert not worker.is_alive() and not queued.is_alive() and second.is_set()


def test_invalid_velocity_cannot_be_mistaken_for_arrival(backend):
    original = backend.request

    def request(path, data=None):
        result = original(path, data)
        if path.endswith("/pose-target"):
            backend.state["joint_velocity"][1] = float("nan")
        return result

    backend.request = request
    with pytest.raises(RuntimeError, match="joint velocity"):
        backend.move_tcp([0.45, 0.0, 0.2])
    assert backend.calls[-1][0].endswith("/stop")


@pytest.mark.parametrize("steps", [1, 5])
def test_eef_chunk_uses_same_goal_and_does_not_wait_for_arrival(backend, steps):
    backend.eef_chunk_control = True
    original = backend.request

    def request(path, data=None):
        if path.endswith("eef-chunk"):
            backend.calls.append((path, data))
            return {
                "held": True,
                "reached": False,
                "executed_steps": steps,
                "ticks": [{"index": i + 1} for i in range(steps)],
                "measured_pose": list(backend.state["tcp_pose"]),
            }
        return original(path, data)

    backend.request = request
    result = backend.move_eef([0.41, 0, 0.2], [0, 1, 0, 0], steps)
    assert result["held"] and not result["reached"] and backend.armed
    sent = [data for path, data in backend.calls if path.endswith("eef-chunk")]
    assert sent == [{"pose": [0.41, 0, 0.2, 0, 1, 0, 0], "steps": steps}]
    assert not any(path.endswith("pose-target") for path, _ in backend.calls)


@pytest.mark.parametrize(
    "failure", ["disabled", "count", "bool", "table", "rotation", "empty_quaternion"]
)
def test_eef_invalid_or_disabled_sends_no_motion(backend, failure):
    backend.eef_chunk_control = failure != "disabled"
    steps = 6 if failure == "count" else True if failure == "bool" else 1
    position = [0.4, 0, -0.1] if failure == "table" else [0.41, 0, 0.2]
    q = (
        [1, 0, 0, 0]
        if failure == "rotation"
        else []
        if failure == "empty_quaternion"
        else [0, 1, 0, 0]
    )
    with pytest.raises((RuntimeError, ValueError)):
        backend.move_eef(position, q, steps)
    assert all(path.endswith("/state") for path, _ in backend.calls)


def test_eef_pre_execution_rejection_is_returned_without_disarming(backend):
    from robots.flexiv.motion import EEFInputRejected

    backend.eef_chunk_control = True
    original = backend.request

    def request(path, data=None):
        if path.endswith("eef-chunk"):
            raise EEFInputRejected("invalid EEF goal")
        return original(path, data)

    backend.request = request
    result = backend.move_eef([0.41, 0, 0.2], [0, 1, 0, 0], 1)
    assert result["no_execution"] and result["retryable"] and backend.armed


@pytest.mark.parametrize(
    "result", [None, {"held": False}, {"held": True, "executed_steps": 1, "ticks": []}]
)
def test_eef_ambiguous_or_incomplete_execution_stops(backend, result):
    backend.eef_chunk_control = True
    original = backend.request

    def request(path, data=None):
        if path.endswith("eef-chunk"):
            if result is None:
                raise RuntimeError("lost acknowledgement")
            return result
        return original(path, data)

    backend.request = request
    with pytest.raises(RuntimeError):
        backend.move_eef([0.41, 0, 0.2], [0, 1, 0, 0], 1)
    assert not backend.armed and backend.calls[-1][0].endswith("/stop")


@pytest.mark.parametrize("proven", [False, True])
def test_collector_http_rejection_requires_explicit_no_execution(monkeypatch, proven):
    import io
    import json
    from urllib.error import HTTPError

    from robots.flexiv.motion import EEFInputRejected

    body = json.dumps(
        {
            "detail": {
                "error": "target rejected",
                "no_execution": proven,
                "retryable": True,
            }
        }
    ).encode()

    def rejected(*args, **kwargs):
        raise HTTPError("http://unused", 422, "rejected", {}, io.BytesIO(body))

    monkeypatch.setattr("robots.flexiv.env_server.urlopen", rejected)
    backend = CollectorBackend("http://unused")
    expected = EEFInputRejected if proven else RuntimeError
    with pytest.raises(expected):
        backend.request("/rpent/supervised/eef-chunk", {"pose": [0] * 7, "steps": 1})


def test_eef_delta_uses_base_axes_and_fresh_feedback_between_segments(backend):
    from scipy.spatial.transform import Rotation

    backend.eef_chunk_control = True
    q = Rotation.from_euler("xyz", [35, 15, 70], degrees=True).as_quat()
    backend.state["tcp_pose"][3:] = [q[3], *q[:3]]
    reference = list(backend.state["tcp_pose"])
    original = backend.request
    sent = []

    def request(path, data=None):
        if path.endswith("eef-chunk"):
            sent.append(data)
            backend.state["tcp_pose"][0] += 0.001
            return {
                "held": True,
                "reached": False,
                "executed_steps": data["steps"],
                "ticks": [{"index": i + 1} for i in range(data["steps"])],
                "measured_pose": list(backend.state["tcp_pose"]),
            }
        return original(path, data)

    backend.request = request
    translation, rotvec = [0.01, 0.004, 0], [0.06, -0.02, 0.03]
    first = backend.move_eef_delta(translation, rotvec, 5)
    second = backend.move_eef_delta(translation, rotvec, 1)
    expected_rotation = Rotation.from_rotvec(rotvec) * rotation(reference)
    assert len(sent) == 2
    assert [item["steps"] for item in sent] == [5, 1]
    np.testing.assert_allclose(sent[0]["pose"][:3], [0.41, 0.004, 0.2])
    np.testing.assert_allclose(sent[1]["pose"][:3], [0.411, 0.004, 0.2])
    for result, command in zip((first, second), sent):
        np.testing.assert_allclose(
            rotation(command["pose"]).as_matrix(), expected_rotation.as_matrix()
        )
        assert result["frame"] == "robot_base"
        assert result["translation_m"] == translation
        assert result["rotation_vector_rad"] == rotvec
        assert result["requested_target_pose"] == command["pose"]
        assert result["held"] and not result["reached"]
    np.testing.assert_allclose(first["reference_pose"], reference)
    np.testing.assert_allclose(second["reference_pose"][:3], [0.401, 0, 0.2])
    assert first["measured_pose"] != first["requested_target_pose"]
    assert not any(path.endswith("pose-target") for path, _ in backend.calls)


@pytest.mark.parametrize(
    "translation,rotvec,steps",
    [
        ([0, 0], [0, 0, 0], 1),
        ([float("nan"), 0, 0], [0, 0, 0], 1),
        ([0, 0, 0], [0, 0], 1),
        ([0, 0, 0], [0, float("inf"), 0], 1),
        ([0.04, 0.04, 0], [0, 0, 0], 1),
        ([0, 0, 0], [0.15, 0.15, 0], 1),
        ([0, 0, 0], [0, 0, 2 * np.pi], 1),
        ([0, 0, 0], [0, 0, 0], 0),
        ([0, 0, 0], [0, 0, 0], 6),
        ([0, 0, 0], [0, 0, 0], True),
        ([0, 0, 0], [0, 0, 0], 1.0),
    ],
)
def test_invalid_eef_delta_never_sends_motion(backend, translation, rotvec, steps):
    backend.eef_chunk_control = True
    with pytest.raises(ValueError):
        backend.move_eef_delta(translation, rotvec, steps)
    assert all(path.endswith("/state") for path, _ in backend.calls)


@pytest.mark.parametrize("failure", ["disabled", "disarmed", "readonly", "table"])
def test_eef_delta_preserves_existing_motion_gates(backend, failure):
    backend.eef_chunk_control = failure != "disabled"
    if failure == "disarmed":
        backend.armed = False
    elif failure == "readonly":
        backend.connection["motion_enabled"] = False
    elif failure == "table":
        backend.state["tcp_pose"][2] = 0.02
    with pytest.raises((RuntimeError, ValueError)):
        backend.move_eef_delta([0, 0, -0.02], [0, 0, 0], 1)
    assert all(path.endswith("/state") for path, _ in backend.calls)


def test_rejected_eef_delta_keeps_reference_and_target_evidence(backend):
    from robots.flexiv.motion import EEFInputRejected

    backend.eef_chunk_control = True
    original = backend.request

    def request(path, data=None):
        if path.endswith("eef-chunk"):
            raise EEFInputRejected("target rejected before execution")
        return original(path, data)

    backend.request = request
    result = backend.move_eef_delta([0.01, 0, 0], [0, 0, 0], 1)
    assert result["no_execution"] and result["retryable"] and backend.armed
    assert result["frame"] == "robot_base"
    assert result["reference_pose"] == backend.state["tcp_pose"]
    np.testing.assert_allclose(result["requested_target_pose"][:3], [0.41, 0, 0.2])
