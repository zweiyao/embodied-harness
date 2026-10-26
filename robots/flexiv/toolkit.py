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

import numpy as np
from PIL import Image, ImageDraw

from rpent.session import EnvState
from rpent.tools import ToolResult
from rpent.tools.base import tool
from rpent.tools.toolkit import Toolkit


class FlexivToolkit(Toolkit):
    def __init__(self, *, env, output_dir, dashboard_events, memory):
        self.env = env
        self._observation_lock = threading.RLock()
        super().__init__(
            dashboard_events=dashboard_events,
            memory=memory,
            state=EnvState(Path(output_dir)),
        )
        self.add_tool(self.observe)
        if env.meta.get("calibrated_readonly"):
            self.add_tool(self.view_perception_setup)
            self.add_tool(self.localize_target)
        if env.meta["motion_enabled"]:
            self.add_tool(self.move_delta)
            if env.meta.get("supervised_control"):
                self.add_tool(self.move_tcp)
                self.add_tool(self.align_tool_down)
                self.add_tool(self.set_gripper)
                self.add_tool(self.stop_motion)
                if env.meta.get("home_available"):
                    self.add_tool(self.reset_home)
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
            camera: wrist or side; choose a view showing the whole target.
            pixel: Interior surface [x,y] pixel in the original full-resolution image.
            box: Whole target [x0,y0,x1,y1] box; reject clipped/occluded targets.

        Do not select the hole of a ring-shaped object or background inside a
        bounding box. Do not invent boxes around clipped fragments. This tool
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
        """Read fresh joint/TCP state and currently available collector camera images."""
        # Toolkit can schedule readonly calls concurrently; state recording cannot.
        with self._observation_lock:
            return self._capture()

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
        obstacles. For grasping, approach from above, descend, then close.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.move_tcp(position_m, quaternion_wxyz))

    @tool
    def align_tool_down(self) -> ToolResult:
        """Point tool +Z toward the calibrated tabletop; preserve projected heading.

        Raise the grasp reference >=50 mm above the tabletop first. The program
        handles bounded orientation segments; no model-supplied intermediate
        quaternions are needed. Gripper opening is preserved. Check that held
        objects and fingers have a clear sweep; no collision model is available.
        """
        self.raise_if_cancelled()
        return ToolResult(data=self.env.align_tool_down())

    @tool
    def set_gripper(self, width_m: float) -> ToolResult:
        """Set the final opening in metres (0..0.098), with measured force feedback.

        Pass the final desired width, e.g. 0.098 to open fully. The program
        handles <=2 mm internal steps; do not split these into model calls.
        A control error stops the experiment: report it, do not retry motion.

        Contact stops further closure and returns contact_detected, not proof
        of a secure grasp. After contact, lift only 5 mm and inspect both images
        before carrying. Use 0.098 to release, then verify the object stayed.
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
