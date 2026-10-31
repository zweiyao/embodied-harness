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

"""Flexiv tools with RPent-owned state artifacts and automatic observations."""

import base64
import io
import re
import threading
from pathlib import Path
from typing import Annotated

import numpy as np
from PIL import Image, ImageDraw
from pydantic import Field

from rpent.session import EnvState
from rpent.tools import ToolResult
from rpent.tools.base import tool
from rpent.tools.toolkit import Toolkit


def tool_methods(meta: dict | None, control_mode: str) -> list[str]:
    """Select method names for registration, or all supported names without meta."""
    if control_mode not in ("native", "eef_delta", "rdk"):
        raise ValueError("Unknown Flexiv control mode")

    def enabled(key):
        return meta is None or bool(meta.get(key))

    methods = ["observe"]
    if control_mode == "rdk" and enabled("tactile_configured"):
        methods.append("tactile_compare")
    if enabled("calibrated_readonly"):
        methods += ["view_perception_setup", "localize_target"]
    if enabled("motion_enabled"):
        if control_mode == "rdk":
            methods += [
                "rdk_move_eef_delta",
                "rdk_move_tcp",
                "rdk_set_gripper",
                "stop_motion",
            ]
        if control_mode == "native":
            methods.append("move_delta")
        if control_mode != "rdk" and enabled("supervised_control"):
            if control_mode == "eef_delta":
                methods.append("move_eef_delta")
            else:
                methods.append("move_tcp")
                if enabled("eef_chunk_control"):
                    methods.append("move_eef")
                methods.append("align_tool_down")
            methods += ["set_gripper", "stop_motion"]
            if enabled("home_available") and control_mode == "native":
                methods.append("reset_home")
    return methods


class FlexivToolkit(Toolkit):
    def __init__(
        self, *, env, output_dir, dashboard_events, memory, control_mode="native"
    ):
        if control_mode not in ("native", "eef_delta", "rdk"):
            raise ValueError("Unknown Flexiv control mode")
        if (control_mode == "rdk") != (env.meta.get("control_backend") == "rdk"):
            raise ValueError("rdk control mode requires the direct RDK environment")
        if control_mode == "rdk":
            if not isinstance(env.meta.get("motion_enabled"), bool):
                raise ValueError("RDK environment must report motion_enabled")
            if env.meta.get("reset_before_task"):
                raise ValueError("rdk requires reset_before_task=false")
        if control_mode == "eef_delta":
            if not all(
                env.meta.get(key)
                for key in ("motion_enabled", "supervised_control", "eef_chunk_control")
            ):
                raise ValueError(
                    "eef_delta requires a supervised EEF-enabled environment"
                )
            if env.meta.get("reset_before_task"):
                raise ValueError("eef_delta requires reset_before_task=false")
        self.env = env
        self._observation_lock = threading.RLock()
        super().__init__(
            dashboard_events=dashboard_events,
            memory=memory,
            state=EnvState(Path(output_dir)),
        )
        for method in tool_methods(env.meta, control_mode):
            self.add_tool(getattr(self, method))
        try:
            self.observe()
            if env.meta.get("reset_before_task") and env.meta["motion_enabled"]:
                result = self.execute_tool("reset_home", {})
                if result.is_error:
                    raise RuntimeError(f"Experiment startup home failed: {result.data}")
        except Exception:
            self.env.close()
            raise

    def _capture(self, command=None, result=None, elapsed_s=None):
        observed = self.env.get_observation()
        images = []
        info = {
            k: v
            for k, v in observed.items()
            if k not in ("images_jpeg", "images_png", "depths")
        }
        with self.state.record_step(
            state=observed["state"],
            command=command,
            result=result,
            elapsed_s=elapsed_s,
            extras={"native_success": None},
        ) as index:
            if "tactile" in observed:
                self.state.save("tactile.json", observed["tactile"])
            calibration = observed.get("camera_calibration")
            if calibration is not None:
                self.state.save("perception.json", calibration)
                # Keep full geometry in the recorded step for localization and
                # view_perception_setup; routine results need only its summary.
                info["camera_calibration"] = {
                    key: value
                    for key, value in calibration.items()
                    if key not in {"cameras", "state", "source_sha256"}
                }
                info["camera_calibration"]["cameras"] = {
                    role: {
                        **{
                            key: value
                            for key, value in camera.items()
                            if key not in {"intrinsics", "T_base_camera"}
                        },
                        "image_size": [
                            camera["intrinsics"]["width"],
                            camera["intrinsics"]["height"],
                        ],
                    }
                    for role, camera in calibration["cameras"].items()
                }
            for role, depth in observed.get("depths", {}).items():
                self.state.save(f"{role}_depth.npy", depth)
            for name, encoded in observed.get(
                "images_png", observed.get("images_jpeg", {})
            ).items():
                # Collector uses its logical camera names, not user-supplied paths.
                safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
                picture = Image.open(io.BytesIO(base64.b64decode(encoded))).convert(
                    "RGB"
                )
                self.state.save(f"{safe}.png", np.asarray(picture))
                buf = io.BytesIO()
                picture.save(buf, format="PNG")
                images.append(buf.getvalue())
        info.update(step=index, action_result=result, native_success=None)
        if command is None:
            self._publish_step(self.state.get(index))
        return ToolResult(data=info, images=images)

    @tool(readonly=True)
    def view_perception_setup(self, step: int) -> ToolResult:
        """Read calibration and native-TCP/grasp-reference semantics for an observed step."""
        return ToolResult(data=self.state.load("perception.json", step=step))

    @tool(readonly=True)
    def localize_target(
        self,
        step: int,
        target: str,
        camera: str,
        pixel: list[float],
        box: list[float],
    ) -> ToolResult:
        """Locate a visible target surface using its recorded color-aligned depth.

        Args:
            step: Exact observe step; do not mix images from different steps.
            target: Named object and surface feature, not just its color.
            camera: wrist or side; choose a view showing the entire named surface feature.
            pixel: Interior surface [x,y] pixel in the original full-resolution image.
            box: Visible feature [x0,y0,x1,y1] box inside the image, enclosing the pixel.

        Do not select the hole of a ring-shaped object or background inside a
        bounding box. Name the visible feature; do not invent hidden geometry.
        Other object regions may be occluded. Invalid depth is a read-only query
        failure: reselect a valid surface point, view or observation. This tool
        estimates a surface point; it neither detects objects nor commands motion.
        """
        from robots.flexiv.perception import back_project

        if step < 0 or not target.strip():
            raise ValueError(
                "Provide the exact nonnegative step and a named physical feature"
            )
        if camera not in ("wrist", "side"):
            raise ValueError("Choose wrist or side")
        if (
            self.env.meta.get("motion_enabled")
            and self.env.meta.get("calibration_provisional")
            and camera != "side"
            and camera not in self.env.meta.get("operator_confirmed_cameras", [])
        ):
            raise ValueError(
                "Use side for this provisional control session; wrist is observation-only"
            )
        with self._observation_lock:
            metadata = self.state.load("perception.json", step=step)
            depth = self.state.load(f"{camera}_depth.npy", step=step)
            result = back_project(metadata, depth, camera, pixel, box)
            result.update(step=step, target=target, pixel=pixel, box=box)
            # Each attempt gets a separate record, preserving earlier selections.
            images = []
            with self.state.record_step(
                state=metadata["state"],
                command={"tool": "localize_target", "source_step": step},
                result=result,
            ) as index:
                result["record_step"] = index
                self.state.save("localization.json", result)
                picture = Image.open(
                    self.state.artifact_path(f"{camera}.png", step=step)
                ).convert("RGB")
                draw = ImageDraw.Draw(picture)
                draw.rectangle(box, outline="yellow", width=3)
                x, y = pixel
                draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline="red", width=3)
                self.state.save(f"{camera}_selected.png", np.asarray(picture))
                buffer = io.BytesIO()
                picture.save(buffer, format="PNG")
                images.append(buffer.getvalue())
            self._publish_step(self.state.get(index))
            return ToolResult(data=result, images=images)

    @tool(readonly=True)
    def observe(self) -> ToolResult:
        """Read joint/TCP state and available RGB-D and left fingertip tactile images."""
        # Toolkit can schedule readonly calls concurrently; state recording cannot.
        with self._observation_lock:
            return self._capture()

    @tool(readonly=True)
    def tactile_compare(self, before_step: int, after_step: int) -> ToolResult:
        """Measure left fingertip surface image motion between two recorded observations.

        Returns displacement in original image pixels (x right, y down), tracking
        quality and evidence steps. Compare with TCP motion and RGB object pose.
        Neither frame is assumed unloaded. Large motion or poor tracking may be
        ambiguous; this is not calibrated force, robot direction, slip classification
        or an insertion-success judgment.

        Args:
            before_step: Earlier observe/action step containing tactile_left.png.
            after_step: Later observe/action step, ideally immediately after a short action.
        """
        from robots.flexiv.tactile import compare

        if before_step < 0 or after_step <= before_step:
            raise ValueError("Select two recorded observation steps in ascending order")
        with self._observation_lock:
            metadata = [
                self.state.load("tactile.json", step=step)["left"]
                for step in (before_step, after_step)
            ]
            images = [
                np.asarray(
                    Image.open(
                        self.state.artifact_path("tactile_left.png", step=step)
                    ).convert("RGB")
                )
                for step in (before_step, after_step)
            ]
            result = compare(*images, *metadata)
            result.update(before_step=before_step, after_step=after_step, side="left")
            return ToolResult(data=result)

    @tool
    def move_delta(self, xyz: list[float]) -> ToolResult:
        """Submit <= 2 mm translation in the robot BASE frame; preserve orientation.

        Args:
            xyz: Base-frame displacement [dx, dy, dz], metres.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.move_delta(xyz))

    @tool
    def move_tcp(
        self, position_m: list[float], quaternion_wxyz: list[float] | None = None
    ) -> ToolResult:
        """Move native TCP to an absolute base-frame position, at most 50 mm per call.

        Args:
            position_m: Absolute [x,y,z] in robot-base metres, inside reported workspace.
            quaternion_wxyz: Optional unit [w,x,y,z]; omit to preserve orientation.

        Uses a native smooth trajectory at <=20 mm/s, with measured arrival feedback.
        At most 10 degrees per call. Rotation requires >=50 mm table clearance;
        translation retains >=4 mm grasp-reference clearance. Gripper opening is
        preserved. Check both images after each move. This does not plan around
        obstacles. Select orientation and waypoints for the actual task. An earlier
        localization call is not required when current evidence supports this target.
        Inspect actual motion and object progress before choosing another action.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.move_tcp(position_m, quaternion_wxyz))

    @tool
    def move_eef(
        self,
        position_m: list[float],
        quaternion_wxyz: list[float],
        steps: Annotated[int, Field(ge=1, le=5, strict=True)],
    ) -> ToolResult:
        """Execute one fixed absolute TCP target for 1–5 controls at 25 Hz, then hold and observe.

        Args:
            position_m: Absolute native TCP [x,y,z], robot-base metres, within 50 mm.
            quaternion_wxyz: Explicit unit [w,x,y,z], within 10 degrees of measured TCP.
            steps: Number of 40 ms controls toward this SAME target, not waypoints.

        The native Flexiv controller executes Cartesian goals; no client-side IK.
        Each control uses fresh state. The segment is followed by a stationary
        hold and capture, so total call latency exceeds steps * 0.04 seconds.
        Arrival at the requested target is not guaranteed. Read measured pose,
        tracking error and recorded tick states before choosing the next action.
        Gripper opening is unchanged; use set_gripper(width_m) separately.
        Existing workspace, table, speed and authorization limits still apply.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.move_eef(position_m, quaternion_wxyz, steps))

    @tool
    def move_eef_delta(
        self,
        translation_m: list[float],
        rotation_vector_rad: list[float],
        steps: Annotated[int, Field(ge=1, le=5, strict=True)],
    ) -> ToolResult:
        """Move toward a measured-TCP-relative goal, then hold and return images/state.

        Args:
            translation_m: Base-axis [dx,dy,dz] metres, vector norm <=0.05.
            rotation_vector_rad: Base-axis right-hand rotation vector, radians,
                norm <=10 degrees; [0,0,0] preserves orientation. Not Euler angles.
            steps: 1–5 controls at 25 Hz toward one goal; delta is applied once.

        Target: p + translation_m, Exp(rotation_vector_rad) * R from fresh TCP.
        Actual motion can be smaller than requested. Gripper stays unchanged.
        Existing workspace, table and speed limits apply.
        """
        self.raise_if_cancelled()
        return ToolResult(
            data=self.env.move_eef_delta(translation_m, rotation_vector_rad, steps)
        )

    @tool
    def align_tool_down(self) -> ToolResult:
        """Point tool +Z toward the calibrated tabletop; preserve projected heading.

        Raise the grasp reference >=50 mm above the tabletop first. The program
        handles bounded orientation segments; no model-supplied intermediate
        quaternions are needed. Gripper opening is preserved. Check that held
        objects and fingers have a clear sweep; no collision model is available.
        This optional helper is not required before every grasp or insertion.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.align_tool_down())

    @tool(name="move_tcp")
    def rdk_move_tcp(
        self, position_m: list[float], quaternion_wxyz: list[float] | None = None
    ) -> ToolResult:
        """Move the native TCP to a base-frame pose and return measured arrival feedback.

        Args:
            position_m: Absolute [x,y,z] in robot-base metres.
            quaternion_wxyz: Unit [w,x,y,z]; omit to preserve measured orientation.

        The RDK controller follows one goal until arrival or the command deadline.
        Gripper opening is unchanged. Use the reported control_limits and inspect
        returned state and images before the next action.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.move_tcp(position_m, quaternion_wxyz))

    @tool(name="move_eef_delta")
    def rdk_move_eef_delta(
        self, translation_m: list[float], rotation_vector_rad: list[float]
    ) -> ToolResult:
        """Move by a base-frame translation and rotation-vector increment from measured TCP.

        Resolve the goal once; wait until arrival or the command deadline.
        Gripper opening is unchanged.

        Args:
            translation_m: [dx,dy,dz] in robot-base metres.
            rotation_vector_rad: Base-frame right-hand rotation vector [rx,ry,rz]
                = unit axis * angle in radians, not Euler angles or a quaternion.
                [0,0,0.08726646] rotates 5 degrees about base +Z;
                [0,0,0] preserves orientation.

        The server resolves p_target=p_current+translation_m and
        R_target=Exp(rotation_vector_rad)*R_current once. The RDK follows this
        goal until arrival or the command deadline. Use reported control_limits;
        gripper opening is unchanged. Inspect the returned state and images.
        """
        self.raise_if_cancelled()
        return ToolResult(
            data=self.env.move_eef_delta(translation_m, rotation_vector_rad)
        )

    @tool(name="set_gripper")
    def rdk_set_gripper(self, width_m: float) -> ToolResult:
        """Set the final gripper opening with one native RDK command.

        Args:
            width_m: Desired opening in metres, within the reported device limits.

        Read measured width and force, then inspect object motion. Command
        completion or contact feedback alone does not establish a secure grasp.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.set_gripper(width_m))

    @tool
    def set_gripper(self, width_m: float) -> ToolResult:
        """Set the final opening in metres (0..0.098), with measured force feedback.

        Pass the final desired width, e.g. 0.098 to open fully. The program
        handles <=2 mm internal steps; do not split these into model calls.
        A control error stops the experiment: report it, do not retry motion.

        Contact stops further closure and returns contact_detected, not proof
        of a secure grasp. Inspect the object and actual gripper feedback before
        transport; grasp closure differs from insertion contact. Release only when
        required by the instructed task, then verify the object's resulting state.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.set_gripper(width_m))

    @tool
    def stop_motion(self) -> ToolResult:
        """Stop arm and gripper in place. Only the operator can arm again."""
        return ToolResult(data=self.env.stop_motion())

    @tool
    def reset_home(self) -> ToolResult:
        """Return to the operator-saved joint pose, preserving gripper width.

        Startup runs this automatically when enabled. Do not repeat after a
        successful startup reset. Use only when the operator requests a return
        and the arm's entire return path is clear; there is no collision planner.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.reset_home())

    def get_env_state(self, *, command, result, elapsed_s):
        with self._observation_lock:
            return self._capture(command, result, elapsed_s)

    def cancel_active_and_wait(self):
        with self._scheduler.condition:
            calls = self._scheduler.cancel()
            active = bool(self._scheduler.active)
        try:
            if active and self.env.meta.get("motion_enabled"):
                self.env.stop_motion()
        finally:
            self._scheduler.wait(calls)

    def close(self):
        try:
            super().close()
        finally:
            self.env.close()
