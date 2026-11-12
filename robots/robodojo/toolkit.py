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

"""RoboDojo toolkit: shared perception and backend-specific control tools."""

from __future__ import annotations

import time
import uuid
from functools import partial
from typing import TYPE_CHECKING, Any

from rpent.dashboard.events import DashboardEventSink
from rpent.session import EnvState
from rpent.tools import Toolkit, ToolResult, iter_tools
from rpent.utils.logging import get_output_dir

if TYPE_CHECKING:
    from rpent.memory.manager import MemoryManager


class RoboDojoToolkit(Toolkit):
    """Toolkit for the RoboDojo (Isaac Sim) environment.

    By default every robot tool is registered. The workbench can freeze a native
    allowlist for a dev run. ``eval_fair`` additionally
    requires a mode-validated environment, removes file tools, and disables
    development perception recording. Scoring and safety diagnostics are never
    planner tools.
    """

    def __init__(
        self,
        *,
        primitives_kwargs: dict[str, Any],
        dashboard_events: DashboardEventSink,
        memory: MemoryManager,
        eval_fair: bool = False,
        selected: list[dict] | None = None,
        journal: Any = None,
    ) -> None:
        if selected is not None:
            from robots.robodojo.catalog import validate_selection

            if eval_fair:
                raise ValueError("Selectable RoboDojo workbench tools require dev mode")
            validate_selection(selected)
            self.planner_tools_only = True
        if journal is not None:
            self.journal = journal
        self.eval_fair = eval_fair
        self._owns_env = primitives_kwargs.get("owns_env", False)
        self._task_name = primitives_kwargs.get("task", "")
        if eval_fair and not getattr(primitives_kwargs.get("env"), "eval_fair", False):
            raise ValueError("eval-fair requires a mode-validated environment client")
        state = EnvState(get_output_dir())
        super().__init__(
            dashboard_events=dashboard_events,
            state=state,
            memory=memory,
        )
        self.init_primitives(primitives_kwargs=primitives_kwargs)
        self._register_robodojo_tools()
        if selected is not None:
            names = {item["name"] for item in selected}
            self._tools = {
                name: entry for name, entry in self._tools.items() if name in names
            }
        if eval_fair:
            allowed = {
                "view_env_state",
                "segment",
                "back_project",
                "move_to",
                "set_gripper",
                "pi0_pick",
            }
            self._tools = {
                name: entry for name, entry in self._tools.items() if name in allowed
            }

    def execute_tool(self, name, input_dict):
        journal = getattr(self, "journal", None)
        if journal is None:
            return self._execute_recorded_tool(name, input_dict)
        call_id, started = uuid.uuid4().hex, time.monotonic()
        journal.append(
            "tool_request", {"call_id": call_id, "name": name, "arguments": input_dict}
        )
        try:
            result = self._execute_recorded_tool(name, input_dict)
        except Exception as exc:
            journal.append(
                "tool_error", {"call_id": call_id, "name": name, "error": str(exc)}
            )
            raise
        journal.append(
            "tool_response",
            {
                "call_id": call_id,
                "name": name,
                "result": result.data,
                "images": result.images,
                "elapsed_s": time.monotonic() - started,
            },
        )
        return result

    def _execute_recorded_tool(self, name, input_dict):
        result = super().execute_tool(name, input_dict)
        if not self.eval_fair and name in {
            "segment",
            "back_project",
        }:
            import copy

            if isinstance(result.to_dict(), dict):
                # Read-only queries do not create EnvState steps. Attach them
                # to the next action for Flash grounding; actions themselves
                # are already recorded by the shared Toolkit/EnvState path.
                self._pending_perception.append(
                    copy.deepcopy(
                        {
                            "action": name,
                            "arguments": input_dict,
                            "result": result.to_dict(),
                        }
                    )
                )
        return result

    def flash_observation(self) -> dict:
        """Refresh the public observation used by live Flash grounding."""
        from robots.robodojo.access import public_observation

        if not self.eval_fair:
            raise RuntimeError("Flash requires eval-fair toolkit")
        obs = public_observation(self._primitives.env.get_obs())
        self._primitives._last_obs = obs
        return obs

    def init_primitives(self, *, primitives_kwargs: dict[str, Any]) -> None:
        """Wipe stale run artifacts, build the primitives, dump step 0.

        The env server resets the Isaac Sim scene once at boot, so the client
        does not re-reset here; this only establishes the initial state record.
        """
        from robots.robodojo import tools as robodojo_tools

        self._pending_perception = []
        self._state.reset()
        self._primitives = RoboDojoPrimitives(
            env=primitives_kwargs["env"],
            sam3_client=primitives_kwargs.get("sam3_client"),
            vla_client=primitives_kwargs.get("vla_client"),
            action_type=primitives_kwargs.get("action_type", "joint"),
            check_cancelled=self.raise_if_cancelled,
        )
        self._publish_step(
            robodojo_tools.dump_state(self._primitives, self._state, log=None)
        )

    def close(self) -> None:
        """Close an owned environment; leave a borrowed server running."""
        super().close()
        if self._owns_env:
            self._primitives.env.close()

    def solved(self) -> bool:
        """Read official success for the runner after planner execution."""
        if self.eval_fair:
            return False  # Plan completion is not an official task verdict.
        return self._primitives.env.is_success()

    def _register_robodojo_tools(self) -> None:
        from robots.robodojo import tools as robodojo_tools

        for definition in iter_tools(robodojo_tools):
            resources = {"state": self._state}
            if definition.name != "view_env_state":
                resources["primitives"] = self._primitives
            self.add_tool(definition.with_handler(partial(definition, **resources)))

    def get_env_state(
        self,
        *,
        command: dict[str, Any],
        result: dict[str, Any],
        elapsed_s: float,
    ) -> ToolResult:
        from robots.robodojo import tools as robodojo_tools

        record = robodojo_tools.dump_state(
            self._primitives,
            self._state,
            log={"command": command, "result": result, "elapsed_s": elapsed_s},
            perception=self._pending_perception,
        )
        self._pending_perception = []
        return robodojo_tools.view_env_state(record.step_idx, state=self._state)


class RoboDojoPrimitives:
    """Primitive implementations backed by the RoboDojo env RPC client."""

    def __init__(self, *, env, sam3_client, vla_client, action_type, check_cancelled):
        self.env = env
        self.sam3_client = sam3_client
        self.vla_client = vla_client
        self.action_type = action_type
        self._check_cancelled = check_cancelled
        self._last_obs = None
