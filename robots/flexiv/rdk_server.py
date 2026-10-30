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

"""Standalone HTTP owner of a Flexiv RDK 1.x robot; no collector dependency."""

import argparse
import hashlib
import json
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.spatial.transform import Rotation


class ServerConfig(BaseModel):
    """Deployment settings, never supplied by the planner."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    robot_sn: str
    workspace_min: list[float] = Field(min_length=3, max_length=3)
    workspace_max: list[float] = Field(min_length=3, max_length=3)
    gripper_name: str = "Flexiv-GN01"
    audit_path: str | None = None
    home_reference: str | None = None
    max_linear_vel: float = Field(default=0.02, gt=0)
    max_angular_vel: float = Field(default=0.15, gt=0)
    max_linear_acc: float = Field(default=0.1, gt=0)
    max_angular_acc: float = Field(default=0.5, gt=0)
    max_translation_m: float = Field(default=0.10, gt=0)
    max_rotation_deg: float = Field(default=30, gt=0, le=180)
    arrival_position_m: float = Field(default=0.001, gt=0)
    arrival_angle_deg: float = Field(default=0.5, gt=0)
    timeout_s: float = Field(default=30, gt=0)
    gripper_velocity: float = Field(default=0.02, gt=0)
    gripper_force: float = Field(default=20, gt=0)

    @model_validator(mode="after")
    def check_workspace(self):
        if np.any(np.asarray(self.workspace_min) >= self.workspace_max):
            raise ValueError("workspace_min must be below workspace_max")
        return self


class PoseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    position_m: list[float] = Field(min_length=3, max_length=3)
    quaternion_wxyz: list[float] | None = Field(
        default=None, min_length=4, max_length=4
    )


class DeltaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    translation_m: list[float] = Field(min_length=3, max_length=3)
    rotation_vector_rad: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3
    )


class GripperRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    width_m: float


def _vector(value, size):
    result = np.asarray(value, dtype=float)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(f"Expected {size} finite numbers")
    return result


def _pose(value):
    result = _vector(value, 7)
    if abs(np.linalg.norm(result[3:]) - 1.0) > 1e-3:
        raise ValueError("Expected a unit quaternion in wxyz order")
    return result


def _rotation(pose):
    return Rotation.from_quat(np.roll(pose[3:], -1))


def _load_home(config):
    if config.home_reference is None:
        return None
    raw = Path(config.home_reference).expanduser().read_bytes()
    saved = json.loads(raw)["captured_state"]
    if (
        saved["robot_sn"] != config.robot_sn
        or saved["coordinate_frame"] != "robot_base"
        or saved["quaternion_order"] != "wxyz"
    ):
        raise ValueError("Home reference robot or coordinate frame does not match")
    joints = _vector(saved["joint_position"], 7)
    pose = _pose(saved["tcp_pose"])
    if np.any(pose[:3] < config.workspace_min) or np.any(
        pose[:3] > config.workspace_max
    ):
        raise ValueError("Home reference TCP is outside configured workspace")
    return {
        "target_joints_rad": joints.tolist(),
        "target_tcp_pose": pose.tolist(),
        "reference_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _primitive_reached(value):
    # RDK 1.9 reports an integer 0/1; the strings '0'/'1' are not booleans.
    if not isinstance(value, (bool, np.bool_, int, np.integer)) or value not in (0, 1):
        raise ValueError("Invalid reachedTarget feedback from RDK")
    return value == 1


class DirectRobot:
    """Serialize native commands while allowing an independent stop request."""

    def __init__(self, config: ServerConfig, *, rdk=None, robot=None):
        self.home = _load_home(config)
        if rdk is None:
            import flexivrdk as rdk
        self.config = config
        self.rdk = rdk
        # Construction establishes communication only: never enable, home or init.
        self.robot = robot if robot is not None else rdk.Robot(config.robot_sn)
        self.tool = rdk.Tool(self.robot)
        self.gripper = None
        self.armed = False
        self.stop_reason = "Server started; explicit enable required"
        self._operation = threading.Lock()
        self._dispatch = threading.RLock()
        self._audit_lock = threading.Lock()
        self._generation = 0
        if config.audit_path:
            Path(config.audit_path).expanduser().parent.mkdir(
                parents=True, exist_ok=True
            )

    def _audit(self, event: str, **values) -> None:
        if not self.config.audit_path:
            return
        with self._audit_lock:
            with Path(self.config.audit_path).expanduser().open("a") as stream:
                stream.write(
                    json.dumps(
                        {"time": time.time(), "event": event, **values}, allow_nan=False
                    )
                    + "\n"
                )

    def state(self) -> dict[str, Any]:
        """Return measured data with native frame labels, without enabling motion."""
        native = self.robot.states()
        pose = _pose(native.tcp_pose).tolist()
        state = {
            "robot_sn": self.config.robot_sn,
            "tcp_pose": pose,
            "joint_position": _vector(native.q, 7).tolist(),
            "joint_velocity": _vector(native.dq, 7).tolist(),
            "mode": str(self.robot.mode()),
            "fault": bool(self.robot.fault()),
            "operational": bool(self.robot.operational()),
            "connected": bool(self.robot.connected()),
            "coordinate_frame": "robot_base",
            "quaternion_order": "wxyz",
            "gripper_width_m": None,
            "gripper_force_n": None,
            "gripper_is_moving": None,
        }
        for name in ("tcp_vel", "ext_wrench_in_world", "ext_wrench_in_tcp"):
            if hasattr(native, name):
                state[name] = _vector(getattr(native, name), 6).tolist()
        if self.gripper is not None:
            grip = self.gripper.states()
            values = _vector([grip.width, grip.force], 2)
            state.update(
                gripper_width_m=float(values[0]),
                gripper_force_n=float(values[1]),
                gripper_is_moving=bool(grip.is_moving),
            )
        limits = self.config.model_dump(
            exclude={"audit_path", "robot_sn", "gripper_name", "home_reference"}
        )
        if self.gripper is not None:
            params = self.gripper.params()
            limits["gripper_min_width_m"] = float(params.min_width)
            limits["gripper_max_width_m"] = float(params.max_width)
        return {
            "control_backend": "rdk",
            "armed": self.armed,
            "state": state,
            "tool": {
                "name": self.tool.name(),
                "tcp_location": _pose(self.tool.params().tcp_location).tolist(),
            },
            "gripper_ready": self.gripper is not None,
            "home_available": self.home is not None,
            "stop_reason": self.stop_reason,
            "config": limits,
        }

    @contextmanager
    def _command(self, name, params):
        if not self._operation.acquire(blocking=False):
            raise HTTPException(409, "Another robot command is running")
        with self._dispatch:
            generation = self._generation
        try:
            self._audit("command", command=name, params=params)
            yield generation
        except Exception as exc:
            self._audit("error", command=name, error=str(exc))
            raise
        finally:
            self._operation.release()

    def _check(self, generation, *, armed=True, expected_mode=None):
        if generation != self._generation:
            raise HTTPException(409, "Command cancelled by stop")
        if armed and not self.armed:
            raise HTTPException(409, "Robot is not enabled for this server")
        if not self.robot.connected() or self.robot.fault():
            raise HTTPException(409, "Robot disconnected or reporting a hardware fault")
        if armed and (
            not self.robot.operational()
            or self.robot.mode()
            != (
                self.rdk.Mode.NRT_CARTESIAN_MOTION_FORCE
                if expected_mode is None
                else expected_mode
            )
        ):
            raise HTTPException(
                409, "Robot is not operational in the expected control mode"
            )

    def _send(
        self, generation, function, *args, armed=True, expected_mode=None, **kwargs
    ):
        # Stop and native command submission share this lock. A cancelled command
        # cannot issue any later SDK command, even if its worker resumes afterwards.
        with self._dispatch:
            self._check(generation, armed=armed, expected_mode=expected_mode)
            return function(*args, **kwargs)

    def stop(self, reason="Operator stop") -> dict[str, Any]:
        """Cancel the active operation and stop both native devices."""
        errors = []
        with self._dispatch:
            self._generation += 1
            self.armed = False
            self.stop_reason = reason
            for device in (self.robot, self.gripper):
                if device is not None:
                    try:
                        device.Stop()
                    except Exception as exc:
                        errors.append(str(exc))
        self._audit("stop", reason=reason, errors=errors)
        if errors:
            raise HTTPException(503, {"stop_reason": reason, "errors": errors})
        return {"stopped": True, "armed": False, "stop_reason": reason}

    def _execution_failed(self, generation, exc):
        # Do not overwrite an explicit concurrent stop or issue another command.
        with self._dispatch:
            if generation == self._generation:
                self.stop(str(exc))

    def _bind_gripper(self, generation):
        if self.gripper is not None:
            return
        grip = self.rdk.Gripper(self.robot)
        # A gripper already enabled in Elements must not be enabled twice.
        if grip.params().name != self.config.gripper_name:
            self._send(generation, grip.Enable, self.config.gripper_name, armed=False)
        if grip.params().name != self.config.gripper_name:
            raise RuntimeError("Native gripper name does not match configuration")
        _vector([grip.states().width, grip.states().force], 2)
        self.gripper = grip

    def enable(self) -> dict[str, Any]:
        """Explicit operator activation; does not clear faults or initialize grip."""
        with self._command("enable", {}) as generation:
            try:
                self._send(generation, self.robot.Enable, armed=False)
                deadline = time.monotonic() + self.config.timeout_s
                while not self.robot.operational():
                    self._check(generation, armed=False)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Robot did not become operational")
                    time.sleep(0.05)
                self._bind_gripper(generation)
                if self.tool.name() != self.config.gripper_name:
                    raise RuntimeError(
                        "Active native tool does not match configured gripper; select it in Elements"
                    )
                self._send(
                    generation,
                    self.robot.SwitchMode,
                    self.rdk.Mode.NRT_CARTESIAN_MOTION_FORCE,
                    armed=False,
                )
                with self._dispatch:
                    self._check(generation, armed=False)
                    self.armed = True
                    self.stop_reason = None
                result = self.state()
                self._audit("result", command="enable", result=result)
                return result
            except Exception as exc:
                self._execution_failed(generation, exc)
                raise

    def activate_gripper(self) -> dict[str, Any]:
        """Bind an existing native device; never perform a full-range Init()."""
        with self._command("activate_gripper", {}) as generation:
            self._check(generation, armed=False)
            self._bind_gripper(generation)
            result = self.state()
            self._audit("result", command="activate_gripper", result=result)
            return result

    def home_preview(self) -> dict[str, Any]:
        """Describe the frozen operator reference without enabling or moving."""
        return {
            "available": self.home is not None,
            **(self.home or {"reason": "No saved home_reference configured"}),
            "joint_velocity_scale": 30,
            "timeout_s": self.config.timeout_s,
            "current": self.state(),
            "gripper_commanded": False,
            "collision_checked": False,
        }

    def reset_home(self) -> dict[str, Any]:
        """Execute one native MoveJ to the saved joints, preserving gripper width."""
        with self._command("jointreset", self.home or {}) as generation:
            self._check(generation)
            if self.home is None:
                raise ValueError("No saved home_reference configured")
            if self.tool.name() != self.config.gripper_name:
                raise ValueError("Active native tool changed since enable")
            target = np.asarray(self.home["target_joints_rad"])
            primitive_mode = self.rdk.Mode.NRT_PRIMITIVE_EXECUTION
            started = time.monotonic()
            try:
                self._send(generation, self.robot.SwitchMode, primitive_mode)
                self._send(
                    generation,
                    self.robot.ExecutePrimitive,
                    "MoveJ",
                    {
                        "target": self.rdk.JPos(np.rad2deg(target).tolist()),
                        "jntVelScale": 30,
                    },
                    expected_mode=primitive_mode,
                )
                while True:
                    self._check(generation, expected_mode=primitive_mode)
                    reached = _primitive_reached(
                        self.robot.primitive_states().get("reachedTarget")
                    )
                    state = self.state()["state"]
                    error = float(
                        np.max(np.abs(np.asarray(state["joint_position"]) - target))
                    )
                    self._audit("state", command="jointreset", state=state)
                    if (
                        reached
                        and error <= 0.0002
                        and max(abs(v) for v in state["joint_velocity"]) < 0.005
                    ):
                        actual = _pose(state["tcp_pose"])
                        expected = np.asarray(self.home["target_tcp_pose"])
                        position_error = float(
                            np.linalg.norm(actual[:3] - expected[:3])
                        )
                        angle_error = float(
                            np.rad2deg(
                                (
                                    _rotation(actual) * _rotation(expected).inv()
                                ).magnitude()
                            )
                        )
                        if (
                            position_error > self.config.arrival_position_m
                            or angle_error > self.config.arrival_angle_deg
                        ):
                            raise RuntimeError(
                                "Reached joints do not match saved TCP reference; check native tool configuration"
                            )
                        self._send(
                            generation,
                            self.robot.SwitchMode,
                            self.rdk.Mode.NRT_CARTESIAN_MOTION_FORCE,
                            expected_mode=primitive_mode,
                        )
                        with self._dispatch:
                            self._check(generation)
                            result = {
                                "reached": True,
                                "motion": "MoveJ",
                                "commands": 1,
                                **self.home,
                                "joint_velocity_scale": 30,
                                "measured_pose": actual.tolist(),
                                "max_joint_error_rad": error,
                                "position_error_m": position_error,
                                "angle_error_deg": angle_error,
                                "elapsed_s": time.monotonic() - started,
                                "state": self.state()["state"],
                                "gripper_commanded": False,
                            }
                        self._audit("result", command="jointreset", result=result)
                        return result
                    if time.monotonic() - started >= self.config.timeout_s:
                        raise TimeoutError(
                            "MoveJ did not reach the saved reference before timeout"
                        )
                    time.sleep(0.05)
            except Exception as exc:
                self._execution_failed(generation, exc)
                raise

    def _target(self, current, target):
        target = _pose(target)
        c = self.config
        if np.any(target[:3] < c.workspace_min) or np.any(target[:3] > c.workspace_max):
            raise ValueError("Target is outside configured workspace")
        if np.linalg.norm(target[:3] - current[:3]) > c.max_translation_m + 1e-9:
            raise ValueError("Target exceeds maximum translation")
        if (
            np.rad2deg((_rotation(target) * _rotation(current).inv()).magnitude())
            > c.max_rotation_deg + 1e-9
        ):
            raise ValueError("Target exceeds maximum rotation")
        return target

    def move(self, request: PoseRequest | DeltaRequest) -> dict[str, Any]:
        """Resolve one target, submit once, and await measured arrival at it."""
        name = "delta" if isinstance(request, DeltaRequest) else "pose"
        with self._command(name, request.model_dump()) as generation:
            self._check(generation)
            current = _pose(self.robot.states().tcp_pose)
            if isinstance(request, DeltaRequest):
                delta = _vector(request.translation_m, 3)
                rotvec = _vector(request.rotation_vector_rad, 3)
                if (
                    np.linalg.norm(rotvec)
                    > np.deg2rad(self.config.max_rotation_deg) + 1e-9
                ):
                    raise ValueError("Rotation vector exceeds maximum rotation")
                rotation = Rotation.from_rotvec(rotvec) * _rotation(current)
                target = np.r_[current[:3] + delta, np.roll(rotation.as_quat(), 1)]
            else:
                target = np.r_[
                    request.position_m,
                    current[3:]
                    if request.quaternion_wxyz is None
                    else request.quaternion_wxyz,
                ]
            target = self._target(current, target)
            started = time.monotonic()
            try:
                self._send(
                    generation,
                    self.robot.SendCartesianMotionForce,
                    target.tolist(),
                    max_linear_vel=self.config.max_linear_vel,
                    max_angular_vel=self.config.max_angular_vel,
                    max_linear_acc=self.config.max_linear_acc,
                    max_angular_acc=self.config.max_angular_acc,
                )
                while True:
                    self._check(generation)
                    status = self.state()
                    measured = _pose(status["state"]["tcp_pose"])
                    distance = float(np.linalg.norm(measured[:3] - target[:3]))
                    angle = float(
                        np.rad2deg(
                            (_rotation(measured) * _rotation(target).inv()).magnitude()
                        )
                    )
                    self._audit("state", command=name, state=status["state"])
                    if (
                        distance <= self.config.arrival_position_m
                        and angle <= self.config.arrival_angle_deg
                        and max(abs(v) for v in status["state"]["joint_velocity"])
                        < 0.005
                    ):
                        with self._dispatch:
                            self._check(generation)
                            result = {
                                "reached": True,
                                "commands": 1,
                                "target_pose": target.tolist(),
                                "measured_pose": measured.tolist(),
                                "position_error_m": distance,
                                "angle_error_deg": angle,
                                "elapsed_s": time.monotonic() - started,
                                "state": status["state"],
                            }
                        self._audit("result", command=name, result=result)
                        return result
                    if time.monotonic() - started >= self.config.timeout_s:
                        raise TimeoutError(
                            "Native Cartesian target was not reached before timeout"
                        )
                    time.sleep(0.02)
            except Exception as exc:
                self._execution_failed(generation, exc)
                raise

    def move_gripper(self, request: GripperRequest) -> dict[str, Any]:
        """Issue one native Move, retaining native force-limited finger behavior."""
        with self._command("move_gripper", request.model_dump()) as generation:
            self._check(generation)
            if self.gripper is None:
                raise HTTPException(409, "Activate the gripper first")
            params = self.gripper.params()
            width = float(request.width_m)
            if (
                not np.isfinite(width)
                or not params.min_width <= width <= params.max_width
            ):
                raise ValueError("Width is outside native gripper limits")
            if (
                not params.min_vel <= self.config.gripper_velocity <= params.max_vel
                or not params.min_force <= self.config.gripper_force <= params.max_force
            ):
                raise ValueError("Configured gripper speed/force exceeds native limits")
            before = float(self.gripper.states().width)
            started = time.monotonic()
            quiet_since = None
            previous = before
            try:
                self._send(
                    generation,
                    self.gripper.Move,
                    width,
                    self.config.gripper_velocity,
                    self.config.gripper_force,
                )
                while True:
                    self._check(generation)
                    grip = self.gripper.states()
                    actual, force = _vector([grip.width, grip.force], 2)
                    moving = bool(grip.is_moving) or abs(actual - previous) > 0.0001
                    previous = actual
                    quiet_since = (
                        None
                        if moving
                        else (
                            quiet_since if quiet_since is not None else time.monotonic()
                        )
                    )
                    reached = bool(abs(actual - width) <= 0.0005 and not moving)
                    stopped_short = (
                        quiet_since is not None
                        and time.monotonic() - quiet_since >= 0.5
                    )
                    self._audit(
                        "state",
                        command="move_gripper",
                        width_m=float(actual),
                        force_n=float(force),
                        is_moving=bool(grip.is_moving),
                    )
                    if reached or stopped_short:
                        if not reached:
                            self._send(generation, self.gripper.Stop)
                        with self._dispatch:
                            self._check(generation)
                            result = {
                                "reached": reached,
                                "commands": 1,
                                "width_m": float(actual),
                                "force_n": float(force),
                                "stopped_short": bool(not reached),
                                "reason": "target_reached"
                                if reached
                                else "stationary_before_target",
                                "elapsed_s": time.monotonic() - started,
                            }
                        self._audit("result", command="move_gripper", result=result)
                        return result
                    if time.monotonic() - started >= self.config.timeout_s:
                        raise TimeoutError(
                            "Native gripper command did not finish before timeout"
                        )
                    time.sleep(0.02)
            except Exception as exc:
                self._execution_failed(generation, exc)
                raise


def create_app(controller: DirectRobot) -> FastAPI:
    """Expose synchronous RDK calls in workers so stop can interrupt waiting."""

    @asynccontextmanager
    async def lifespan(app):
        yield
        if controller.armed:
            controller.stop("Robot server shutdown")

    app = FastAPI(title="RPent direct Flexiv RDK server", lifespan=lifespan)

    def call(function, *args):
        try:
            return function(*args)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(504, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/health")
    def health():
        return {
            "service": "flexiv-rdk",
            "connected": controller.robot.connected(),
            "armed": controller.armed,
        }

    @app.get("/state")
    def state():
        return call(controller.state)

    @app.post("/enable")
    def enable():
        return call(controller.enable)

    @app.post("/activate_gripper")
    def activate_gripper():
        return call(controller.activate_gripper)

    @app.get("/home-preview")
    def home_preview():
        return call(controller.home_preview)

    @app.post("/jointreset")
    def jointreset():
        return call(controller.reset_home)

    @app.post("/pose")
    def pose(request: PoseRequest):
        return call(controller.move, request)

    @app.post("/delta")
    def delta(request: DeltaRequest):
        return call(controller.move, request)

    @app.post("/move_gripper")
    def move_gripper(request: GripperRequest):
        return call(controller.move_gripper, request)

    @app.post("/stop")
    def stop():
        return call(controller.stop)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    config = ServerConfig.model_validate_json(
        Path(args.config).expanduser().read_text()
    )
    import uvicorn

    with robot_owner_lock(config.robot_sn):
        uvicorn.run(create_app(DirectRobot(config)), host=args.host, port=args.port)


@contextmanager
def robot_owner_lock(robot_sn: str):
    """Reject a second server process before it connects to the same robot."""
    import fcntl

    identity = hashlib.sha256(robot_sn.replace(" ", "").encode()).hexdigest()[:24]
    with open(f"/tmp/rpent-flexiv-rdk-{identity}.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another direct RDK server owns this robot") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


if __name__ == "__main__":
    main()
