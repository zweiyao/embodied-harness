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

"""Bounded 25 Hz EEF segments on the collector's existing Flexiv owner.

Installed as collector/core/eef_chunk.py. It never enables or reconnects hardware.
"""

import threading
import time

import numpy as np
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool


class EEFChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pose: list[float] = Field(min_length=7, max_length=7)
    steps: int = Field(ge=1, le=5, strict=True)


class EEFChunks:
    period_s = 0.04
    hold_timeout_s = 3.0

    def __init__(self, motion):
        self.motion = motion
        self._operation = threading.Lock()
        self._command = threading.RLock()
        self._epoch = 0
        self._owner_thread = None

    @property
    def active(self):
        return self._owner_thread is not None

    def guard(self):
        if self.active and self._owner_thread != threading.get_ident():
            raise HTTPException(
                409, "EEF segment owns the arm; wait for its hold receipt"
            )

    def cancel(self):
        # Serialize cancellation against Send, so a stop cannot be followed by
        # an already-validated target sent by this segment's worker.
        with self._command:
            self._epoch += 1

    def _check_owner(self, epoch):
        if self._epoch != epoch or not self.motion.armed:
            raise RuntimeError("EEF segment interrupted; no automatic resume")

    def _state(self, token, epoch):
        result = self.motion.feedback(token)
        self._check_owner(epoch)
        state = result["state"]
        pose, q, dq = (
            np.asarray(state[k], float)
            for k in ("tcp_pose", "joint_position", "joint_velocity")
        )
        if (
            pose.shape != (7,)
            or q.shape != (7,)
            or dq.shape != (7,)
            or not np.isfinite(np.r_[pose, q, dq]).all()
            or state["fault"]
            or not state["operational"]
            or state["mode"] != "Mode.NRT_CARTESIAN_MOTION_FORCE"
            or abs(np.linalg.norm(pose[3:]) - 1) > 1e-3
            or not np.isfinite(state["gripper_force_n"])
            or abs(state["gripper_force_n"]) > 22
            or state["gripper_is_moving"]
        ):
            raise RuntimeError("Invalid EEF control feedback or gripper force")
        return state

    def _send(self, robot, pose, epoch):
        with self._command:
            self._check_owner(epoch)
            robot._robot.SendCartesianMotionForce(
                list(pose),
                max_linear_vel=0.02,
                max_angular_vel=0.15,
                max_linear_acc=0.1,
                max_angular_acc=0.5,
            )

    def execute(self, token, target, steps):
        if not self._operation.acquire(blocking=False):
            raise HTTPException(
                409,
                {
                    "error": "Another EEF segment is active",
                    "no_execution": True,
                    "retryable": True,
                },
            )
        self._owner_thread = threading.get_ident()
        epoch, started, ticks = self._epoch, False, []
        try:
            # Everything before the first Send is a non-executing rejection.
            try:
                command = EEFChunk(pose=target, steps=steps)
                robot, state, pose = self.motion.ready(token)
                goal = np.asarray(command.pose, float)
                if (
                    abs(np.linalg.norm(goal[3:]) - 1) > 1e-3
                    or np.max(np.abs(state["joint_velocity"])) > 0.01
                    or np.linalg.norm(goal[:3] - pose[:3]) > 0.050001
                    or self.motion.angle(pose[3:], goal[3:]) > np.deg2rad(10.000001)
                    or np.any(goal[:3] < robot._workspace_min + 0.004)
                    or np.any(goal[:3] > robot._workspace_max - 0.004)
                ):
                    raise HTTPException(
                        422,
                        "EEF target violates pose, range or stationary-start limits",
                    )
                self._state(token, epoch)
            except RuntimeError:
                if self.motion.armed:
                    self.motion.halt("EEF initial feedback check failed")
                raise
            except (ValueError, HTTPException) as error:
                code = getattr(error, "status_code", 422)
                raise HTTPException(
                    code,
                    {
                        "error": str(getattr(error, "detail", error)),
                        "no_execution": True,
                        "retryable": code == 422,
                    },
                ) from error
            began = time.monotonic()
            prior_q = np.asarray(state["joint_position"], float)
            self.motion.audit(
                "eef_begin", target=goal.tolist(), steps=steps, state=state
            )
            with self._command:
                self._check_owner(epoch)
                self.motion.pending_pose = goal.copy()
                self.motion.command_deadline = (
                    began + steps * self.period_s + self.hold_timeout_s + 1.0
                )
                started = True  # Even a failed Send may have an uncertain ACK.
            for index in range(steps):
                self._send(robot, goal, epoch)
                deadline = began + (index + 1) * self.period_s
                time.sleep(max(0.0, deadline - time.monotonic()))
                state = self._state(token, epoch)
                now = time.monotonic()
                if now - deadline > self.period_s:
                    raise RuntimeError(
                        "EEF 25 Hz deadline missed by more than one period"
                    )
                q = np.asarray(state["joint_position"], float)
                if np.max(np.abs(q - prior_q)) > 0.05:
                    raise RuntimeError(
                        "Measured joint change exceeded 0.05 rad per EEF tick"
                    )
                prior_q = q
                tick = {
                    "index": index + 1,
                    "elapsed_s": now - began,
                    "deadline_lateness_s": now - deadline,
                    "state": state,
                }
                ticks.append(tick)
                self.motion.audit("eef_tick", **tick)
            segment_s = time.monotonic() - began
            # End the old goal, not the authorization. Hold a measured pose and
            # wait only for hold settling, never for arrival at the original goal.
            hold_pose = np.asarray(state["tcp_pose"], float)
            with self._command:
                self._check_owner(epoch)
                self.motion.pending_pose = hold_pose.copy()
                self._send(robot, hold_pose, epoch)
            hold_began, stable = time.monotonic(), 0
            while time.monotonic() - hold_began < self.hold_timeout_s:
                time.sleep(0.02)
                state = self._state(token, epoch)
                current = np.asarray(state["tcp_pose"], float)
                d = float(np.linalg.norm(current[:3] - hold_pose[:3]))
                a = self.motion.angle(current[3:], hold_pose[3:])
                if d > 0.005 or a > np.deg2rad(1.0):
                    raise RuntimeError("Stationary hold drift exceeded 5 mm / 1 degree")
                settled = (
                    d <= 0.00035
                    and a <= np.deg2rad(0.12)
                    and max(map(abs, state["joint_velocity"])) < 0.005
                )
                stable = stable + 1 if settled else 0
                if stable >= 2:
                    with self._command:
                        self._check_owner(epoch)
                        self.motion.pending_pose, self.motion.command_deadline = (
                            None,
                            0.0,
                        )
                    error_m = float(np.linalg.norm(current[:3] - goal[:3]))
                    error_rad = self.motion.angle(current[3:], goal[3:])
                    result = {
                        "held": True,
                        "requested_steps": steps,
                        "executed_steps": len(ticks),
                        "control_dt_s": self.period_s,
                        "segment_elapsed_s": segment_s,
                        "hold_elapsed_s": time.monotonic() - hold_began,
                        "ticks": ticks,
                        "requested_pose": goal.tolist(),
                        "hold_pose": hold_pose.tolist(),
                        "measured_pose": current.tolist(),
                        "translation_error_m": error_m,
                        "angle_error_rad": error_rad,
                        "reached": bool(
                            error_m <= 0.00035 and error_rad <= np.deg2rad(0.12)
                        ),
                    }
                    self.motion.audit("eef_end", **result)
                    return result
            raise RuntimeError("EEF segment stationary hold did not settle")
        except BaseException:
            if started and self._epoch == epoch and self.motion.armed:
                self.motion.halt("EEF segment failed or interrupted")
            raise
        finally:
            self._owner_thread = None
            self._operation.release()


def install_eef_chunks(motion):
    controller = EEFChunks(motion)
    motion.eef_chunks = controller

    @motion.bridge.collector.app.post("/rpent/supervised/eef-chunk")
    async def eef_chunk(command: EEFChunk, request: Request):
        # Keep the operator's stop route responsive during the short segment.
        return await run_in_threadpool(
            controller.execute,
            request.headers.get("X-RPent-Session"),
            command.pose,
            command.steps,
        )

    return controller
