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

"""Direct control uses only RDK routes; opening an environment never enables it."""

from types import SimpleNamespace

import pytest

from robots.flexiv.env_client import FlexivEnvClient
from robots.flexiv.env_server import FlexivEnvFacade
from robots.flexiv.rdk_backend import RdkBackend


def backend(armed=True):
    calls = []
    status = {
        "armed": armed,
        "stop_reason": None,
        "state": {"robot_sn": "test", "tcp_pose": [0.5, 0, 0.3, 1, 0, 0, 0]},
        "tool": {"name": "test", "tcp_location": [0, 0, 0.19, 1, 0, 0, 0]},
        "config": {"timeout_s": 30, "max_translation_m": 0.1},
    }
    instance = RdkBackend("http://unused")

    def request(path, data=None):
        calls.append((path, data))
        return status if path == "/state" else {"reached": True}

    instance.request = request
    return instance, status, calls


def test_open_and_observe_do_not_enable_or_connect_to_collector():
    instance, _, calls = backend(False)
    instance.open()
    assert instance.get_env_meta()["control_backend"] == "rdk"
    assert instance.get_env_meta()["motion_enabled"] is False
    assert instance.get_observation()["missing_cameras"] == ["side", "wrist"]
    instance.close()
    assert calls == [("/state", None), ("/state", None)]


def test_direct_targets_and_gripper_are_forwarded_once():
    instance, _, calls = backend()
    instance.open()
    instance.move_eef_delta([0.03, 0, 0], [0, 0, 0.1])
    instance.move_tcp([0.6, 0, 0.3])
    instance.set_gripper(0.05)
    assert calls[1:] == [
        ("/delta", {"translation_m": [0.03, 0, 0], "rotation_vector_rad": [0, 0, 0.1]}),
        ("/pose", {"position_m": [0.6, 0, 0.3], "quaternion_wxyz": None}),
        ("/move_gripper", {"width_m": 0.05}),
    ]
    instance.close()
    instance.close()
    assert calls.count(("/stop", {})) == 1


def test_readonly_session_rejects_control_even_if_operator_enables_later():
    instance, _, calls = backend(False)
    instance.open()
    with pytest.raises(RuntimeError, match="observation-only"):
        instance.move_eef_delta([0.01, 0, 0], [0, 0, 0])
    assert calls == [("/state", None)]


def test_transport_timeout_stops_without_retrying_relative_action():
    instance, _, calls = backend()
    instance.open()
    request = instance.request

    def failing(path, data=None):
        if path == "/delta":
            calls.append((path, data))
            raise TimeoutError("reply unavailable")
        return request(path, data)

    instance.request = failing
    with pytest.raises(TimeoutError):
        instance.move_eef_delta([0.01, 0, 0], [0, 0, 0])
    assert [p for p, _ in calls] == ["/state", "/delta", "/stop"]


def test_rpc_has_no_collector_helpers_and_stop_can_interrupt():
    instance, _, calls = backend()
    facade = FlexivEnvFacade(instance)
    assert set(facade._rpc) == {
        "env.open",
        "env.close",
        "env.get_env_meta",
        "env.get_observation",
        "env.move_tcp",
        "env.move_eef_delta",
        "env.set_gripper",
        "env.stop_motion",
    }
    facade._dispatch_nosession("env.stop_motion", [], {})
    assert calls == [("/stop", {})]


def test_client_omits_steps_only_for_direct_calls():
    calls = []

    def call(name, **kwargs):
        calls.append((name, kwargs))
        return {}

    client = FlexivEnvClient(SimpleNamespace(call=call))
    client.move_eef_delta([0.02, 0, 0], [0, 0, 0])
    assert "steps" not in calls[-1][1]["kwargs"]
    client.move_eef_delta([0.02, 0, 0], [0, 0, 0], 5)
    assert calls[-1][1]["kwargs"]["steps"] == 5


def test_calibration_snapshot_uses_native_tool_and_measured_state():
    instance, status, calls = backend()
    snapshot = instance.calibration_snapshot()
    assert snapshot["tool"] == status["tool"]
    assert snapshot["state_before"] == status["state"]
    assert snapshot["state_after"] == status["state"]
    assert calls == [("/state", None)]


def test_direct_client_deadlines_exceed_server_deadline():
    calls = []

    def call(name, **kwargs):
        calls.append((name, kwargs))
        return {"control_backend": "rdk", "control_limits": {"timeout_s": 300}}

    client = FlexivEnvClient(SimpleNamespace(call=call))
    client.move_tcp([0.4, 0, 0.3])
    client.move_eef_delta([0.01, 0, 0], [0, 0, 0])
    client.set_gripper(0.05)
    assert [kwargs["timeout_s"] for _, kwargs in calls[-3:]] == [315, 315, 315]
