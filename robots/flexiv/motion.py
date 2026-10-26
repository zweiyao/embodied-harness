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

"""Bounded, feedback-driven actions through the collector's single hardware owner."""

import json
import time

import numpy as np
from scipy.spatial.transform import Rotation


def rotation(pose):
    return Rotation.from_quat([*pose[4:], pose[3]])


def pose_error(actual, target):
    return (
        float(np.linalg.norm(np.asarray(actual[:3]) - target[:3])),
        float((rotation(actual) * rotation(target).inv()).magnitude()),
    )


class BoundedControl:
    """The operator arms separately; actions never enable, initialize or home."""

    def _control_state(self):
        result = self.request("/rpent/supervised/state")
        state = result["state"]
        if (
            not result["armed"]
            or state["fault"]
            or not state["operational"]
            or state["mode"] != "Mode.NRT_CARTESIAN_MOTION_FORCE"
        ):
            raise RuntimeError("Control stopped; operator must inspect and arm again")
        pose = np.asarray(state["tcp_pose"], float)
        velocity = np.asarray(state["joint_velocity"], float)
        if (
            pose.shape != (7,)
            or velocity.shape != (7,)
            or not np.isfinite(np.r_[pose, velocity]).all()
            or abs(np.linalg.norm(pose[3:]) - 1) > 1e-3
        ):
            raise RuntimeError("Invalid measured pose or joint velocity feedback")
        if not np.isfinite(state["gripper_force_n"]):
            raise RuntimeError("Invalid gripper force feedback")
        return state

    def _trace(self, event, **values):
        if self.control_log_dir:
            self.control_log_dir.mkdir(parents=True, exist_ok=True)
            with (self.control_log_dir / "actions.jsonl").open("a") as handle:
                handle.write(
                    json.dumps(
                        dict(time=time.time(), event=event, **values), allow_nan=False
                    )
                    + "\n"
                )

    def _require_motion(self):
        if (
            not self.supervised
            or not self.session
            or not self.connection
            or not self.connection["motion_enabled"]
        ):
            raise RuntimeError(
                "This experiment is observation-only; motion is unavailable"
            )

    def stop_motion(self):
        if not self.session:
            raise RuntimeError("No owned experiment session")
        result = self.request("/rpent/supervised/stop", {})
        self._trace("stop", result=result)
        return result

    def _failed_motion(self, error):
        self._trace("error", error=str(error))
        try:
            self.stop_motion()
        except Exception as stop_error:
            self._trace("stop_error", error=str(stop_error))

    def reset_home(self):
        """Return to the operator-recorded joints without opening the gripper."""
        self._require_motion()
        self._control_state()
        started = time.monotonic()
        try:
            while time.monotonic() - started < 1800:
                result = self.request("/rpent/supervised/home-step", {})
                self._trace("home_step", result=result)
                if result.get("reached") is True:
                    return result
                if result.get("motion") == "MoveJ":
                    # The collector submits once and checks actual feedback on every poll.
                    time.sleep(0.1)
                    continue
                deadline, settled = time.monotonic() + 30, 0
                while time.monotonic() < deadline:
                    time.sleep(0.1)
                    feedback = self.request("/rpent/supervised/state")
                    state = feedback["state"]
                    if (
                        not feedback["armed"]
                        or state["fault"]
                        or not state["operational"]
                    ):
                        raise RuntimeError(
                            "Joint home stopped; operator recovery required"
                        )
                    q = np.asarray(state["joint_position"], float)
                    dq = np.asarray(state["joint_velocity"], float)
                    if (
                        q.shape != (7,)
                        or dq.shape != (7,)
                        or not np.isfinite(np.r_[q, dq]).all()
                    ):
                        raise RuntimeError("Invalid joint home feedback")
                    self._trace("home_feedback", state=state)
                    stable = (
                        np.max(np.abs(q - result["target_joints_rad"])) <= 0.0002
                        and np.max(np.abs(dq)) < 0.005
                    )
                    settled = settled + 1 if stable else 0
                    if settled >= 2:
                        break
                else:
                    raise RuntimeError("Joint home step did not settle")
            raise RuntimeError("Joint home exceeded 1800 seconds")
        except BaseException as error:
            self._failed_motion(error)
            raise

    def table_geometry(self, state):
        board = np.asarray(self.calibration.data["T_base_board"], float)
        normal = getattr(self, "_table_normal", None)
        if normal is None:
            normal = board[:3, 2].copy()
            if normal @ (np.asarray(state["tcp_pose"][:3]) - board[:3, 3]) < 0:
                normal *= -1
            # Freeze the accepted side; crossing the plane must not flip "up".
            self._table_normal = normal
        reference = np.asarray(state["tcp_pose"][:3]) + rotation(
            state["tcp_pose"]
        ).apply(self.calibration.offset)
        return normal, float(normal @ (reference - board[:3, 3]))

    def align_tool_down(self):
        """Align tool +Z toward the calibrated table, preserving projected heading."""
        self._require_motion()
        state = self._control_state()
        normal, clearance = self.table_geometry(state)
        if clearance < 0.05:
            raise ValueError(
                "Raise grasp reference >=50 mm above table before alignment"
            )
        z_axis = -normal
        old_x = rotation(state["tcp_pose"]).as_matrix()[:, 0]
        x_axis = old_x - z_axis * (old_x @ z_axis)
        if np.linalg.norm(x_axis) < 0.1:
            raise ValueError("Current heading cannot define a table-down orientation")
        x_axis /= np.linalg.norm(x_axis)
        y_axis = np.cross(z_axis, x_axis)
        target_rotation = Rotation.from_matrix(
            np.column_stack((x_axis, y_axis, z_axis))
        )
        # Keep one model call: use bounded native goals rather than microscopic steps.
        commands, started = 0, time.monotonic()
        for _ in range(20):
            if time.monotonic() - started > 210:
                break
            current = self._control_state()["tcp_pose"]
            remaining = (target_rotation * rotation(current).inv()).as_rotvec()
            angle = float(np.linalg.norm(remaining))
            if angle <= np.deg2rad(0.12):
                return {
                    "reached": True,
                    "measured_pose": current,
                    "angle_error_deg": float(np.rad2deg(angle)),
                    "commands": commands,
                }
            increment = remaining * min(1.0, np.deg2rad(9.9) / angle)
            q = (Rotation.from_rotvec(increment) * rotation(current)).as_quat()
            result = self.move_tcp(state["tcp_pose"][:3], [q[3], *q[:3]])
            commands += result["commands"]
        error = RuntimeError("Table alignment did not converge")
        self._failed_motion(error)
        raise error

    def move_tcp(self, position_m, quaternion_wxyz=None):
        self._require_motion()
        state = self._control_state()
        initial = np.asarray(state["tcp_pose"], float)
        position = np.asarray(position_m, float)
        quaternion = np.asarray(
            quaternion_wxyz if quaternion_wxyz else initial[3:], float
        )
        if (
            position.shape != (3,)
            or quaternion.shape != (4,)
            or not np.isfinite(position).all()
            or not np.isfinite(quaternion).all()
            or abs(np.linalg.norm(quaternion) - 1) > 0.001
        ):
            raise ValueError("Use finite XYZ metres and a unit wxyz quaternion")
        target = np.r_[position, quaternion]
        if np.any(
            position < np.asarray(self.connection["workspace_min"]) + 0.004
        ) or np.any(position > np.asarray(self.connection["workspace_max"]) - 0.004):
            raise ValueError("Target must retain 4 mm native TCP workspace margin")
        distance, angle = pose_error(initial, target)
        if distance > 0.050001 or angle > np.deg2rad(10):
            raise ValueError(
                "One tool call is limited to 50 mm and 10 degrees; use intermediate waypoints"
            )
        normal, clearance = self.table_geometry(state)
        board_origin = np.asarray(self.calibration.data["T_base_board"], float)[:3, 3]
        # Translation is linear. The offset sphere bounds every intermediate rotation;
        # it is a grasp-reference/table check, not a finger/object collision model.
        target_height = float(normal @ (target[:3] - board_origin))
        if angle > np.deg2rad(0.2):
            lowest = min(float(normal @ (initial[:3] - board_origin)), target_height)
            if lowest - np.linalg.norm(self.calibration.offset) < 0.05:
                raise ValueError(
                    "Rotation requires >=50 mm table clearance along the motion"
                )
        else:
            target_reference = target[:3] + rotation(target).apply(
                self.calibration.offset
            )
            lowest = min(clearance, float(normal @ (target_reference - board_origin)))
            # Cover tiny rotations even when they are below the coarse-rotation gate.
            lowest -= 2 * np.linalg.norm(self.calibration.offset) * np.sin(angle / 2)
            if lowest < 0.004:
                raise ValueError(
                    "Translation must retain >=4 mm grasp-reference table clearance"
                )
        self._trace("move_begin", target=target.tolist(), state=state)
        try:
            response = self.request(
                "/rpent/supervised/pose-target", {"pose": target.tolist()}
            )
            self._trace("pose_target", request=target.tolist(), response=response)
            deadline, settled = time.monotonic() + 30, 0
            while time.monotonic() < deadline:
                time.sleep(0.05)
                state = self._control_state()
                self._trace("feedback", state=state)
                current = np.asarray(state["tcp_pose"], float)
                d, a = pose_error(current, target)
                stable = (
                    d <= 0.00035
                    and a <= np.deg2rad(0.12)
                    and max(map(abs, state["joint_velocity"])) < 0.005
                )
                settled = settled + 1 if stable else 0
                if settled >= 2:
                    result = {
                        "reached": True,
                        "measured_pose": current.tolist(),
                        "translation_error_m": d,
                        "angle_error_deg": float(np.rad2deg(a)),
                        "commands": 1,
                    }
                    self._trace("move_end", result=result)
                    return result
            raise RuntimeError("Measured motion did not settle; experiment stopped")
        except BaseException as error:
            self._failed_motion(error)
            raise

    def _hold_contact(self):
        self.request("/rpent/supervised/gripper-hold", {})
        deadline, widths = time.monotonic() + 5, []
        while time.monotonic() < deadline:
            time.sleep(0.1)
            state = self._control_state()
            widths.append(state["gripper_width_m"])
            if abs(state["gripper_force_n"]) > 22:
                raise RuntimeError("Gripper contact force exceeded limit")
            if (
                not state["gripper_is_moving"]
                and len(widths) >= 5
                and np.ptp(widths[-5:]) < 0.0001
                and max(map(abs, state["joint_velocity"])) < 0.005
            ):
                result = {
                    "reached": False,
                    "measured_width_m": widths[-1],
                    "force_n": state["gripper_force_n"],
                    "contact_detected": True,
                    "object_grasp_verified": False,
                }
                self._trace("contact_hold", result=result)
                return result
        raise RuntimeError("Contact hold did not settle")

    def set_gripper(self, width_m):
        self._require_motion()
        if not np.isfinite(width_m) or not 0 <= width_m <= 0.098:
            raise ValueError("Use gripper opening between 0 and 0.098 metres")
        state = self._control_state()
        self._trace("gripper_begin", target_width_m=width_m, state=state)
        try:
            for _ in range(55):
                start = state["gripper_width_m"]
                if abs(width_m - start) <= 0.0005:
                    return {
                        "reached": True,
                        "measured_width_m": start,
                        "contact_detected": False,
                        "object_grasp_verified": False,
                    }
                closing = width_m < start
                # Contact already exists: do not repeatedly tighten an object.
                if closing and abs(state["gripper_force_n"]) >= 5:
                    return self._hold_contact()
                target = start + float(np.clip(width_m - start, -0.002, 0.002))
                response = self.request(
                    "/rpent/supervised/gripper-step", {"width_m": target}
                )
                self._trace("gripper_step", target_width_m=target, response=response)
                deadline, widths = time.monotonic() + 3, []
                while True:
                    time.sleep(0.02)
                    state = self._control_state()
                    actual, force = state["gripper_width_m"], state["gripper_force_n"]
                    self._trace("gripper_feedback", state=state)
                    if (
                        not np.isfinite(actual)
                        or abs(actual - start) > 0.0035
                        or (target - start) * (actual - start)
                        < -0.0005 * abs(target - start)
                        or abs(force) > 22
                    ):
                        raise RuntimeError(
                            "Gripper feedback exceeded direction, travel or force limits"
                        )
                    if closing and abs(force) >= 5:
                        return self._hold_contact()
                    widths.append(actual)
                    if (
                        not state["gripper_is_moving"]
                        and len(widths) >= 5
                        and np.ptp(widths[-5:]) < 0.0001
                        and abs(actual - target) <= 0.0008
                    ):
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError("Gripper failed to settle")
            raise RuntimeError("Gripper step budget exhausted")
        except BaseException as error:
            self._failed_motion(error)
            raise
