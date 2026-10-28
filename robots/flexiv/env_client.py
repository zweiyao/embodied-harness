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

"""Explicit observation-only connect: no simulator-style reset on hardware."""

from rpent.robots.components.env_client_base import BaseEnvClient


class FlexivEnvClient(BaseEnvClient):
    def __init__(self, client):
        self._client = client
        client.call("env.open", timeout_s=40)
        try:
            self.meta = client.call("env.get_env_meta", timeout_s=40)
        except Exception:
            self.close()
            raise
        self.last_obs = None

    def get_observation(self):
        self.last_obs = self._client.call("env.get_observation", timeout_s=40)
        return self.last_obs

    def move_delta(self, xyz):
        return self._client.call("env.move_delta", kwargs={"xyz": xyz}, timeout_s=40)

    def move_tcp(self, position_m, quaternion_wxyz=None):
        return self._client.call(
            "env.move_tcp",
            kwargs={"position_m": position_m, "quaternion_wxyz": quaternion_wxyz},
            timeout_s=270,
        )

    def move_eef(self, position_m, quaternion_wxyz, steps):
        return self._client.call(
            "env.move_eef",
            kwargs={
                "position_m": position_m,
                "quaternion_wxyz": quaternion_wxyz,
                "steps": steps,
            },
            timeout_s=40,
        )

    def move_eef_delta(self, translation_m, rotation_vector_rad, steps):
        return self._client.call(
            "env.move_eef_delta",
            kwargs={
                "translation_m": translation_m,
                "rotation_vector_rad": rotation_vector_rad,
                "steps": steps,
            },
            timeout_s=40,
        )

    def align_tool_down(self):
        return self._client.call("env.align_tool_down", timeout_s=270)

    def set_gripper(self, width_m):
        return self._client.call(
            "env.set_gripper", kwargs={"width_m": width_m}, timeout_s=180
        )

    def stop_motion(self):
        return self._client.call("env.stop_motion", timeout_s=40)

    def reset_home(self):
        return self._client.call("env.reset_home", timeout_s=1850)

    def reset(self):
        raise RuntimeError(
            "Flexiv reset/homing requires the operator; no automatic reset"
        )

    def close(self):
        return self._client.call("env.close", timeout_s=45)
