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

"""Offline integration tests against the installed SDK and Harness, not loop mocks."""

from __future__ import annotations

import asyncio
import copy
import json
import queue
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic_ai import (
    BinaryContent,
    ModelRequest,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import RetryPromptPart
from pydantic_ai.models.function import DeltaThinkingPart, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

from rpent.dashboard.events import RunStartedEvent, TranscriptEvent, UsageEvent
from rpent.dashboard.state import DashboardState
from rpent.planner.api_loop import ApiAgentLoop
from rpent.session import EnvState
from rpent.tools import Toolkit, ToolResult, common
from rpent.tools import tool as declare_tool

FINISH_ARGS = {"status": "success", "summary": "done"}


class Events:
    enabled = True

    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class RobotToolkit(Toolkit):
    def __init__(self, events, state=None):
        self.calls = []
        super().__init__(dashboard_events=events, memory=SimpleNamespace(), state=state)

    def _register_common_tools(self):
        self.add_tool(common.CommonTools.finish.with_handler(self.finish))
        self.register(
            "observe", lambda: ToolResult(data={"position": 1}, images=[b"image"])
        )

    def register(self, name, handler, declaration=None):
        declaration = declaration or declare_tool(name=name, readonly=True)(handler)

        def run(**kwargs):
            result = handler(**kwargs)
            return result if isinstance(result, ToolResult) else ToolResult(data=result)

        self.add_tool(declaration.with_handler(run), replace=name in self._tools)

    def finish(self, status, summary):
        return ToolResult(data={"_finish": True, "status": status, "summary": summary})

    def execute_tool(self, name, input_dict):
        self.calls.append((name, input_dict))
        return super().execute_tool(name, input_dict)


@pytest.fixture(autouse=True)
def local_tools(monkeypatch):
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr("rpent.planner.api_loop.substitute", lambda value: value)
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")


def tool(name, args=None, index=0):
    return {index: DeltaToolCall(name=name, json_args=json.dumps(args or {}))}


def finish():
    return tool("finish", FINISH_ARGS)


def solve(tmp_path, model, toolkit=None, events=None, **kwargs):
    events = events or Events()
    toolkit = toolkit or RobotToolkit(events)
    config = {
        key: kwargs.pop(key)
        for key in (
            "max_tokens",
            "timeout_s",
            "no_images",
            "reasoning_effort",
            "interactive",
            "require_finish",
            "recent_image_history",
        )
        if key in kwargs
    }
    planner = ApiAgentLoop(model=model, dashboard_events=events, **config)
    result = planner.solve(
        system_prompt="Use the robot toolkit. Finish when done.",
        user_message="Do the task.",
        toolkit=toolkit,
        max_turns=kwargs.pop("max_turns", 10),
        **kwargs,
    )
    return result, toolkit, events


def dashboard(tmp_path):
    state = DashboardState(
        output_dir=tmp_path,
        dashboard_spec={
            "task": {
                "command": "/rpent-task",
                "usage": "/rpent-task <seed>",
                "fields": ({"name": "seed", "kind": "integer", "minimum": 0},),
                "display": "{seed}",
                "output_slug": "s{seed}",
            },
            "runtime_components": (),
            "frame_channels": (),
            "primitives": (),
        },
    )
    state.shared_services_ready()
    state.submit_input("/rpent-task 0")
    assert state.wait_for_task(timeout=0) is not None
    state.emit(RunStartedEvent())
    return state


def user_texts(messages):
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]


def test_finish_returns_transcript_for_rpent_without_step_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    model = TestModel(call_tools=[], custom_output_args=FINISH_ARGS)
    result, toolkit, _ = solve(tmp_path, model)
    assert result.error is None
    assert result.finish_result == {"_finish": True, **FINISH_ARGS}
    assert toolkit.calls == [("finish", FINISH_ARGS)]
    assert result.stats["turns_used"] == 1
    assert [m["role"] for m in result.messages] == ["user", "assistant", "tool"]
    assert result.messages[0] == {"role": "user", "content": "Do the task."}
    call = result.messages[1]["content"][0]
    assert call["name"] == "finish"
    assert call["input"] == FINISH_ARGS
    returned = result.messages[2]
    assert returned["tool_call_id"] == call["id"]
    assert json.loads(returned["content"]) == {"_finish": True, **FINISH_ARGS}
    assert not list(tmp_path.iterdir())
    assert model.last_model_request_parameters.output_tools[0].name == "finish"
    assert "finish" not in [
        t.name for t in model.last_model_request_parameters.function_tools
    ]


@pytest.mark.parametrize("request_timeout_s", [None, 0.05])
def test_opt_in_model_timeout_covers_stalled_response_stream(
    tmp_path, request_timeout_s
):
    events = Events()
    toolkit = RobotToolkit(events)
    toolkit.model_request_timeout_s = request_timeout_s
    stream_closed = []

    async def stream(messages, info):
        try:
            yield "starting"
            await asyncio.sleep(0.15)
            yield finish()
        finally:
            stream_closed.append(True)

    result, _, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), toolkit, events, timeout_s=2
    )
    assert stream_closed == [True]
    if request_timeout_s is None:
        assert result.error is None
        assert result.finish_result == {"_finish": True, **FINISH_ARGS}
    else:
        assert "model response timed out after 0.05s" in result.error
        assert result.finish_result is None
        assert toolkit.calls == []


def test_model_response_timeout_excludes_tool_execution(tmp_path):
    events = Events()
    toolkit = RobotToolkit(events)
    toolkit.model_request_timeout_s = 0.1
    toolkit.register("slow_tool", lambda: (time.sleep(0.25), "done")[1])

    async def stream(messages, info):
        yield finish() if toolkit.calls else tool("slow_tool")

    result, _, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), toolkit, events, timeout_s=2
    )
    assert result.error is None
    assert result.finish_result == {"_finish": True, **FINISH_ARGS}
    assert [name for name, _ in toolkit.calls] == ["slow_tool", "finish"]


@pytest.mark.parametrize("require_finish", [False, True])
def test_refused_finish_retries_without_claiming_success(tmp_path, require_finish):
    events = Events()
    toolkit = RobotToolkit(events)
    attempts = []

    def guarded_finish(**args):
        attempts.append(args)
        if len(attempts) <= 2:
            return {"error": "finish refused; verify the environment"}
        return {"_finish": True, **args}

    toolkit.register("finish", guarded_finish, common.CommonTools.finish)
    histories = []

    async def stream(messages, info):
        histories.append(copy.deepcopy(messages))
        yield finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        events,
        require_finish=require_finish,
    )
    assert result.error is None
    assert len(attempts) == 3
    assert result.stats["turns_used"] == 3
    assert result.finish_result == {"_finish": True, **FINISH_ARGS}
    assert "finish refused" in repr(histories[1])
    assert "finish refused" in json.dumps(result.messages)


@pytest.mark.parametrize("require_finish", [False, True])
def test_persistent_finish_refusal_stops_at_request_budget(tmp_path, require_finish):
    events = Events()
    toolkit = RobotToolkit(events)
    toolkit.register(
        "finish",
        lambda **args: {"error": "finish refused"},
        common.CommonTools.finish,
    )

    async def stream(messages, info):
        yield finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        events,
        max_turns=3,
        require_finish=require_finish,
    )
    assert result.finish_result is None
    assert result.error is None
    assert result.stats["turns_used"] == 3
    assert len(toolkit.calls) == 3


def test_anthropic_request_retains_all_prompt_cache_controls(tmp_path, monkeypatch):
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    model = AnthropicModel(
        "claude-sonnet-4-5", provider=AnthropicProvider(api_key="offline-test")
    )
    requests = []

    async def capture(**kwargs):
        requests.append(kwargs)
        raise RuntimeError("offline request captured")

    monkeypatch.setattr(model.client.beta.messages, "create", capture)
    result, _, _ = solve(tmp_path, model, max_tokens=321)
    assert result.error == "RuntimeError: offline request captured"
    assert len(requests) == 1
    request = requests[0]
    assert request["max_tokens"] == 321
    assert request["system"][0]["text"] == "Use the robot toolkit. Finish when done."
    assert request["system"][-1]["cache_control"]["type"] == "ephemeral"
    assert request["tools"][-1]["cache_control"]["type"] == "ephemeral"
    assert (
        request["messages"][-1]["content"][-1]["cache_control"]["type"] == "ephemeral"
    )
    assert request["tool_choice"]["disable_parallel_tool_use"] is False


@pytest.mark.parametrize("no_images", [False, True])
def test_multimodal_tool_results_and_dashboard_events(tmp_path, no_images):
    histories = []

    async def stream(messages, info):
        histories.append(copy.deepcopy(messages))
        if len(histories) == 1:
            yield {0: DeltaThinkingPart(content="Inspect the scene.")}
            yield tool("observe", index=1)
        else:
            yield "Ready."
            yield finish()

    result, _, events = solve(
        tmp_path, FunctionModel(stream_function=stream), no_images=no_images
    )
    assert result.error is None
    returns = [
        part
        for message in histories[1]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    images = [
        item
        for part in returns
        for item in part.content
        if isinstance(item, BinaryContent)
    ]
    assert bool(images) is not no_images
    if images:
        assert images[0].data == b"image"
    else:
        assert "Image omitted" in repr(returns)
    transcript = [e.payload for e in events.events if isinstance(e, TranscriptEvent)]
    assert {p["type"] for p in transcript} >= {
        "user",
        "thinking",
        "text",
        "tool_call",
        "tool_result",
    }
    assert all("aW1hZ2U=" not in str(p) for p in transcript)
    usage = [event for event in events.events if isinstance(event, UsageEvent)][-1]
    assert usage.tool_calls == 2
    assert result.stats["total_input_tokens"] == usage.inp > 0
    assert result.stats["total_output_tokens"] == usage.out > 0
    serialized = json.dumps(result.messages)
    assert "Inspect the scene." in serialized
    assert "Ready." in serialized
    assert "aW1hZ2U=" not in serialized
    assert any(m.get("name") == "observe" for m in result.messages)


@pytest.fixture
def image_state(tmp_path):
    state = EnvState(tmp_path / "state")
    for value in (0, 255):
        with state.record_step(state={}):
            for name in ("camera.png", "camera.jpg", "camera.jpeg"):
                image = np.full((4, 4, 3), value, dtype=np.uint8)
                assert state.save(name, image) == name
    assert state.save("notes.json", {"position": 1}, step=0) == "notes.json"
    return state


@pytest.mark.parametrize("no_images", [False, True])
@pytest.mark.parametrize(
    "name,step,media_type",
    [
        ("camera.png", None, "image/png"),
        ("camera.jpg", 0, "image/jpeg"),
        ("camera.jpeg", 1, "image/jpeg"),
    ],
)
def test_read_image_returns_saved_artifact_and_records_call(
    tmp_path, image_state, monkeypatch, no_images, name, step, media_type
):
    events = Events()
    toolkit = RobotToolkit(events, state=image_state)
    arguments = {"name": name}
    if step is not None:
        arguments["step"] = step
    resolved_step = image_state.latest_step if step is None else step
    expected_bytes = image_state.load_bytes(name, step=resolved_step)
    histories = []

    if no_images:

        def unexpected_read(*args, **kwargs):
            pytest.fail("--no-images should not read image bytes")

        monkeypatch.setattr(image_state, "load_bytes", unexpected_read)

    async def stream(messages, info):
        histories.append(copy.deepcopy(messages))
        yield tool("read_image", arguments) if len(histories) == 1 else finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        events,
        no_images=no_images,
    )
    assert result.error is None
    assert result.finish_result == {"_finish": True, **FINISH_ARGS}
    returned = next(
        part
        for message in histories[1]
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "read_image"
    )
    assert returned.content["artifact"] == name
    assert returned.content["step"] == resolved_step
    images = [
        item
        for message in histories[1]
        for part in message.parts
        if isinstance(part, (ToolReturnPart, UserPromptPart))
        and isinstance(part.content, list)
        for item in part.content
        if isinstance(item, BinaryContent)
    ]
    if no_images:
        assert not images
        assert "--no-images" in returned.content["notice"]
    else:
        assert len(images) == 1
        assert images[0].data == expected_bytes
        assert images[0].media_type == media_type
    assert result.stats["tool_calls"] == 2
    recorded = next(m for m in result.messages if m.get("name") == "read_image")
    assert recorded["tool_call_id"] == returned.tool_call_id
    assert json.loads(recorded["content"]) == returned.content
    transcript = [e.payload for e in events.events if isinstance(e, TranscriptEvent)]
    assert [p["type"] for p in transcript if p.get("tool") == "read_image"] == [
        "tool_call",
        "tool_result",
    ]


@pytest.mark.parametrize(
    "name,step,error",
    [
        ("missing.png", 0, "not available"),
        ("notes.json", 0, "not an image"),
        ("../camera.png", 0, "base filename"),
        ("camera.png", 99, "not present"),
        ("unregistered.png", 0, "not available"),
        ("camera.png", 0, "not available"),
    ],
)
def test_read_image_errors_reach_model_without_ending_run(
    tmp_path, image_state, name, step, error
):
    events = Events()
    toolkit = RobotToolkit(events, state=image_state)
    image_state.artifact_path("camera.png", step=0).unlink()
    unregistered = image_state.artifact_path("unregistered.png", step=0)
    unregistered.parent.mkdir()
    unregistered.write_bytes(b"not registered in the step")
    histories = []

    async def stream(messages, info):
        histories.append(copy.deepcopy(messages))
        if len(histories) == 1:
            yield tool("read_image", {"name": name, "step": step})
        else:
            yield finish()

    result, _, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), toolkit, events
    )
    assert result.error is None
    assert result.finish_result == {"_finish": True, **FINISH_ARGS}
    returned = next(
        part
        for message in histories[1]
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "read_image"
    )
    assert error in returned.content["error"]


def test_schema_validation_and_sequential_physical_tools(tmp_path):
    events = Events()
    toolkit = RobotToolkit(events, state=EnvState(tmp_path))
    toolkit.get_env_state = lambda **kwargs: ToolResult(data=kwargs["result"])
    positions = []

    @declare_tool
    def move(position: int) -> ToolResult:
        positions.append(position)
        return ToolResult(data={"position": position})

    toolkit.add_tool(move)
    calls = 0

    async def stream(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield tool("move", {"position": "bad"})
        elif calls == 2:
            yield tool("move", {"position": 1}) | tool("move", {"position": 2}, 1)
        else:
            yield finish()

    result, _, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), toolkit, events
    )
    assert result.error is None
    assert positions == [1, 2]
    assert len(toolkit.calls) == 3  # Only validated calls reach the Toolkit.
    assert [m["name"] for m in result.messages if m["role"] == "tool"] == [
        "move",
        "move",
        "finish",
    ]


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ({"row": "470", "col": "255"}, {"row": 470, "col": 255}),
        (
            {"row_range": "[440, 500]", "col_range": "[720, 870]"},
            {"row_range": [440, 500], "col_range": [720, 870]},
        ),
        (
            {"row_range": ["440", "500"], "z_min": "-0.2"},
            {"row_range": [440, 500], "z_min": -0.2},
        ),
        ({"row": 470, "col": None}, {"row": 470, "col": None}),
    ],
)
def test_quoted_numeric_tool_arguments_keep_raw_model_output(
    tmp_path, arguments, expected
):
    events = Events()
    toolkit = RobotToolkit(events)
    received = []

    @declare_tool(readonly=True)
    def back_project(
        row: int | None = None,
        col: int | None = None,
        row_range: list[int] | None = None,
        col_range: list[int] | None = None,
        z_min: float | None = None,
        camera: str = "agentview",
    ) -> ToolResult:
        received.append((row, col, row_range, col_range, z_min, camera))
        return ToolResult(data={"ok": True})

    toolkit.add_tool(back_project)
    arguments = {**arguments, "camera": "007"}
    expected = {**expected, "camera": "007"}
    calls = 0

    async def stream(messages, info):
        nonlocal calls
        calls += 1
        yield tool("back_project", arguments) if calls == 1 else finish()

    result, _, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), toolkit, events
    )
    assert result.error is None
    assert toolkit.calls[0] == ("back_project", expected)
    assert received == [
        tuple(
            expected.get(key)
            for key in ("row", "col", "row_range", "col_range", "z_min", "camera")
        )
    ]
    raw = [
        part
        for message in result.messages
        if message["role"] == "assistant"
        for part in message["content"]
        if part["type"] == "tool_use"
    ]
    assert raw[0]["input"] == arguments


@pytest.mark.parametrize(
    "invalid", ["470px", "row=470", "1.5", "true", "null", "NaN", "Infinity"]
)
def test_invalid_numeric_strings_still_require_model_retry(tmp_path, invalid):
    events = Events()
    toolkit = RobotToolkit(events)
    received = []

    @declare_tool(readonly=True)
    def pixel(row: int | None) -> ToolResult:
        received.append(row)
        return ToolResult(data={"row": row})

    toolkit.add_tool(pixel)
    calls = 0

    async def stream(messages, info):
        nonlocal calls
        calls += 1
        if calls <= 2:
            yield tool("pixel", {"row": invalid if calls == 1 else 470})
        else:
            yield finish()

    result, _, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), toolkit, events
    )
    assert result.error is None
    assert calls == 3
    assert received == [470]


@pytest.mark.parametrize("require_finish", [False, True])
def test_finish_skips_sibling_actions_using_native_end_strategy(
    tmp_path, require_finish
):
    async def stream(messages, info):
        yield finish() | tool("observe", index=1)

    result, toolkit, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), require_finish=require_finish
    )
    assert result.error is None
    assert [name for name, _ in toolkit.calls] == ["finish"]
    assert [m["name"] for m in result.messages if m["role"] == "tool"] == ["finish"]


@pytest.mark.parametrize("mode", ["normal", "terminal", "dashboard"])
def test_request_budget_stops_normally_without_claiming_success(tmp_path, mode):
    async def stream(messages, info):
        yield tool("observe")

    state = dashboard(tmp_path) if mode == "dashboard" else None
    result, toolkit, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        events=state,
        max_turns=2,
        interactive=mode == "terminal",
        dashboard_interaction=state,
    )
    assert result.error is None
    assert result.finish_result is None
    assert result.stats["turns_used"] == 2
    assert len(toolkit.calls) == 2
    assert len([m for m in result.messages if m["role"] == "tool"]) == 2


def test_other_usage_limit_failures_remain_errors(tmp_path):
    async def stream(messages, info):
        raise UsageLimitExceeded("provider-specific limit")
        yield  # pragma: no cover

    result, _, _ = solve(tmp_path, FunctionModel(stream_function=stream), max_turns=1)
    assert result.error.startswith("UsageLimitExceeded: provider-specific limit")
    assert result.finish_result is None


def test_harness_compacts_long_history(tmp_path):
    lengths = []

    async def stream(messages, info):
        lengths.append(len(messages))
        yield tool("observe") if len(lengths) < 45 else finish()

    result, _, _ = solve(tmp_path, FunctionModel(stream_function=stream), max_turns=50)
    assert result.error is None
    assert any(after < before for before, after in zip(lengths, lengths[1:]))
    assert result.messages[0] == {"role": "user", "content": "Do the task."}
    assert len([m for m in result.messages if m["role"] == "assistant"]) == 45
    assert len([m for m in result.messages if m.get("name") == "observe"]) == 44


def test_dashboard_steering_enters_next_request_in_same_native_run(tmp_path):
    state = dashboard(tmp_path)
    sent = []
    histories = []

    async def stream(messages, info):
        histories.append(copy.deepcopy(messages))
        if len(histories) == 1:
            sent.append(state.submit_input("Look left first."))
            await asyncio.sleep(0.05)
            yield tool("observe")
        else:
            assert "Look left first." in user_texts(messages)
            yield finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        events=state,
        dashboard_interaction=state,
    )
    assert result.error is None
    assert [m["content"] for m in result.messages if m["role"] == "user"] == [
        "Do the task.",
        "Look left first.",
    ]
    assert len(histories) == 2
    assert state.planner_activity == "ended"
    assert state.snapshot()["interaction"]["messages"][0]["status"] == "sent"


def test_dashboard_message_during_finish_is_unsent(tmp_path):
    state = dashboard(tmp_path)
    toolkit = RobotToolkit(state)

    def finish_and_submit(**args):
        state.submit_input("This must not reopen the completed task.")
        time.sleep(0.05)
        return {"_finish": True, **args}

    toolkit.register("finish", finish_and_submit, common.CommonTools.finish)
    result, _, _ = solve(
        tmp_path,
        TestModel(call_tools=[], custom_output_args=FINISH_ARGS),
        toolkit,
        state,
        dashboard_interaction=state,
    )
    assert result.error is None
    assert result.stats["turns_used"] == 1
    assert state.snapshot()["interaction"]["messages"][0]["status"] == "unsent"
    assert "This must not reopen" not in json.dumps(result.messages)


def test_dashboard_interrupt_then_followup_preserves_history(tmp_path):
    state = dashboard(tmp_path)
    calls = 0

    async def stream(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield "Starting inspection."
            state.request_interrupt()
            state.submit_input("Continue with the new instruction.")
            await asyncio.sleep(5)
        else:
            assert "Do the task." in user_texts(messages)
            assert "Continue with the new instruction." in user_texts(messages)
            yield finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        events=state,
        dashboard_interaction=state,
        timeout_s=3,
    )
    assert result.error is None
    assert result.finish_result["status"] == "success"
    assert [m["content"] for m in result.messages if m["role"] == "user"] == [
        "Do the task.",
        "Continue with the new instruction.",
    ]
    assert state.snapshot()["interaction"]["messages"][0]["status"] == "sent"


@pytest.fixture(params=[False, True], ids=["normal", "tool-stops-first"])
def dashboard_interrupt_order(request, monkeypatch):
    if not request.param:
        return
    from rpent.planner.api_loop import _Session

    interrupt = _Session.interrupt

    async def interrupt_after_tool_stop(self):
        # Let the SDK reach the queued sibling tool before Dashboard sends its
        # cancellation token, reproducing the physical-drain scheduling race.
        await asyncio.wait_for(self.run_done.wait(), timeout=1)
        return await interrupt(self)

    monkeypatch.setattr(_Session, "interrupt", interrupt_after_tool_stop)


@pytest.mark.parametrize("require_finish", [False, True])
def test_dashboard_interrupt_drains_tool_before_followup(
    tmp_path, dashboard_interrupt_order, require_finish
):
    state = dashboard(tmp_path)
    toolkit = RobotToolkit(state, state=EnvState(tmp_path / "observations"))
    toolkit.get_env_state = lambda **kwargs: ToolResult(data=kwargs["result"])
    observations = []
    toolkit.register("observe", lambda: observations.append("ran") or ToolResult())
    stopped = threading.Event()
    calls = 0

    def move():
        try:
            state.submit_input("Old instruction 1.")
            state.submit_input("Old instruction 2.")
            while any(
                m["status"] != "sending"
                for m in state.snapshot()["interaction"]["messages"]
            ):
                toolkit.raise_if_cancelled()
                state.wait_for_interaction_change(
                    state.interaction_version, timeout=0.05
                )
            with toolkit._scheduler.condition:
                assert toolkit._scheduler.condition.wait_for(
                    lambda: bool(toolkit._scheduler.pending), timeout=2
                )
            state.request_interrupt()
            state.submit_input("Continue after stopping the move.")
            while True:
                toolkit.raise_if_cancelled()
                time.sleep(0.005)
        finally:
            stopped.set()

    toolkit.register("move", move, declaration=declare_tool(name="move")(move))

    async def stream(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield tool("move") | tool("observe", index=1)
        else:
            assert stopped.is_set()
            assert user_texts(messages) == [
                "Do the task.",
                "Continue after stopping the move.",
            ]
            yield finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        state,
        dashboard_interaction=state,
        timeout_s=3,
        require_finish=require_finish,
    )
    assert result.error is None
    assert result.finish_result["status"] == "success"
    assert observations == []
    assert toolkit.calls[-1][0] == "finish"
    assert [m["status"] for m in state.snapshot()["interaction"]["messages"]] == [
        "unsent",
        "unsent",
        "sent",
    ]


@pytest.mark.parametrize("require_finish", [False, True])
def test_task_replacement_cancels_and_drains_physical_work(
    tmp_path, dashboard_interrupt_order, require_finish
):
    state = dashboard(tmp_path)
    toolkit = RobotToolkit(state, state=EnvState(tmp_path / "observations"))
    toolkit.get_env_state = lambda **kwargs: ToolResult(data=kwargs["result"])
    observations = []
    toolkit.register("observe", lambda: observations.append("ran") or ToolResult())
    stopped = threading.Event()

    def move():
        with toolkit._scheduler.condition:
            assert toolkit._scheduler.condition.wait_for(
                lambda: bool(toolkit._scheduler.pending), timeout=2
            )
        state.submit_input("/rpent-task 1")
        try:
            while True:
                toolkit.raise_if_cancelled()
                time.sleep(0.005)
        finally:
            stopped.set()

    toolkit.register("move", move, declaration=declare_tool(name="move")(move))

    async def stream(messages, info):
        yield tool("move") | tool("observe", index=1)

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        state,
        dashboard_interaction=state,
        timeout_s=3,
        require_finish=require_finish,
    )
    assert result.error is None
    assert stopped.is_set()
    assert observations == []
    assert state.planner_activity == "ended"
    assert result.finish_result is None


@pytest.mark.parametrize("require_finish", [False, True])
def test_timeout_drains_physical_work_and_records_partial_history(
    tmp_path, require_finish
):
    events = Events()
    toolkit = RobotToolkit(events)
    stopped = threading.Event()

    def move():
        try:
            while True:
                toolkit.raise_if_cancelled()
                time.sleep(0.005)
        finally:
            stopped.set()

    toolkit.register("move", move)

    async def stream(messages, info):
        yield tool("move")

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        events,
        timeout_s=0.15,
        require_finish=require_finish,
    )
    assert "timed out" in result.error
    assert stopped.is_set()
    assert result.messages[0] == {"role": "user", "content": "Do the task."}
    assert result.messages[1]["content"][0]["name"] == "move"
    json.dumps(result.messages)


def test_native_terminal_preserves_completed_actions_after_model_failure(
    tmp_path, monkeypatch
):
    import pydantic_ai._cli as cli

    requests = []
    replies = iter(["Inspect the scene.", "Continue after the error.", "/exit"])

    async def read_prompt(*args, **kwargs):
        assert requests, "The preset task must run before the first input prompt."
        return next(replies)

    async def stream(messages, info):
        requests.append(copy.deepcopy(messages))
        if len(requests) == 2:
            yield tool("observe")
        elif len(requests) == 3:
            raise RuntimeError("provider failed after observation")
        else:
            yield "Ready."

    monkeypatch.setattr(cli, "PYDANTIC_AI_HOME", tmp_path / "cli")
    monkeypatch.setattr(
        cli, "PromptSession", lambda **kwargs: SimpleNamespace(prompt_async=read_prompt)
    )
    result, toolkit, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), interactive=True
    )
    assert result.error is None
    assert any(
        isinstance(part, TextPart) and part.content == "Ready."
        for message in requests[-1]
        for part in message.parts
    )
    assert user_texts(requests[-1]) == [
        "Do the task.",
        "Inspect the scene.",
        "Continue after the error.",
    ]
    returns = [
        part
        for message in requests[-1]
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "observe"
    ]
    assert len(returns) == 1
    assert "position" in str(returns[0].content)
    assert any(isinstance(item, BinaryContent) for item in returns[0].content)
    assert toolkit.calls == [("observe", {})]
    assert [m["content"] for m in result.messages if m["role"] == "user"] == user_texts(
        requests[-1]
    )


def test_native_terminal_followups_share_budget_and_clear_recovered_error(
    tmp_path, monkeypatch, capsys
):
    import pydantic_ai._cli as cli

    requests = []
    replies = iter(["Inspect.", "Retry.", "Try after the budget.", "/exit"])

    async def read_prompt(*args, **kwargs):
        return next(replies)

    async def stream(messages, info):
        requests.append(copy.deepcopy(messages))
        if len(requests) == 1:
            yield "Ready."
        elif len(requests) == 2:
            raise RuntimeError("temporary provider failure")
        else:
            yield tool("observe")

    monkeypatch.setattr(cli, "PYDANTIC_AI_HOME", tmp_path / "cli")
    monkeypatch.setattr(
        cli, "PromptSession", lambda **kwargs: SimpleNamespace(prompt_async=read_prompt)
    )
    result, toolkit, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), interactive=True, max_turns=3
    )
    assert len(requests) == result.stats["turns_used"] == 3
    assert toolkit.calls == [("observe", {})]
    assert result.error is None
    assert result.finish_result is None
    assert any(m.get("name") == "observe" for m in result.messages)
    output = " ".join(capsys.readouterr().out.split())
    assert "Use /exit to close the session." in output


def test_legacy_terminal_queue_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="terminal input queue"):
        solve(tmp_path, TestModel(), input_queue=queue.Queue())


def test_native_terminal_and_dashboard_cannot_run_together(tmp_path):
    with pytest.raises(ValueError, match="clai and Dashboard cannot run together"):
        solve(tmp_path, TestModel(), interactive=True, dashboard_interaction=object())


@pytest.mark.parametrize("after_tool", [False, True])
def test_model_failure_preserves_rpent_transcript(tmp_path, after_tool):
    calls = 0

    async def stream(messages, info):
        nonlocal calls
        calls += 1
        if after_tool and calls == 1:
            yield tool("observe")
            return
        raise RuntimeError("provider unavailable")

    result, _, _ = solve(tmp_path, FunctionModel(stream_function=stream))
    assert result.error == "RuntimeError: provider unavailable"
    if after_tool:
        assert [m["role"] for m in result.messages] == ["user", "assistant", "tool"]
        assert result.messages[-1]["name"] == "observe"
    else:
        assert result.messages == [{"role": "user", "content": "Do the task."}]
    json.dumps(result.messages)


def test_factory_passes_interactive_mode(tmp_path, monkeypatch):
    from rpent.planner.base import Planner, build_planner

    model = TestModel(call_tools=[], custom_output_args=FINISH_ARGS)
    monkeypatch.setattr("rpent.planner.base.build_api_model", lambda *args: model)
    planner = build_planner(
        "api",
        output_dir=tmp_path,
        recipe_tag="test",
        robot_name="test",
        model="test:test",
        dashboard_events=Events(),
        interactive=True,
    )
    assert isinstance(planner, ApiAgentLoop)
    assert isinstance(planner, Planner)
    assert planner.interactive is True


def test_offline_http_planner_executes_action_and_finish(tmp_path):
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    from tests.e2e_tests.offline_planner_server import (
        OFFLINE_MODEL_NAME,
        OfflinePlannerServer,
        ScriptedToolCall,
    )

    events = Events()
    toolkit = RobotToolkit(events)
    toolkit.register("move", lambda: {"steps": 1})
    script = (
        ScriptedToolCall("move", {}),
        ScriptedToolCall("finish", FINISH_ARGS),
    )
    with OfflinePlannerServer(script) as server:
        model = OpenAIChatModel(
            OFFLINE_MODEL_NAME,
            provider=OpenAIProvider(base_url=server.base_url, api_key="offline-test"),
        )
        result, _, _ = solve(
            tmp_path, model, toolkit=toolkit, events=events, max_turns=2
        )
        assert result.error is None
        assert toolkit.calls == [("move", {}), ("finish", FINISH_ARGS)]
        assert result.finish_result == {"_finish": True, **FINISH_ARGS}
        server.assert_complete()


@pytest.mark.parametrize(
    "model_name,effort,expected",
    [
        ("qwen3.8-max", "none", False),
        ("qwen3.8-flash", "none", False),
        ("qwen3.8-max", "high", True),
        ("gpt-4.1", "none", None),
    ],
)
@pytest.mark.parametrize("require_finish", [False, True])
def test_qwen_thinking_setting_reaches_serialized_http_body(
    tmp_path, model_name, effort, expected, require_finish
):
    import httpx2
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        chunk = {
            "id": "offline",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "finish1",
                                "type": "function",
                                "function": {
                                    "name": "finish",
                                    "arguments": json.dumps(FINISH_ARGS),
                                },
                            }
                        ],
                    },
                }
            ],
        }
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode(),
        )

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    model = OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            base_url="https://example.invalid/v1",
            api_key="offline-test",
            http_client=client,
        ),
    )
    try:
        result, _, _ = solve(
            tmp_path,
            model,
            reasoning_effort=effort,
            max_tokens=8192,
            require_finish=require_finish,
        )
        assert result.error is None
        assert len(bodies) == 1
        body = bodies[0]
        assert body["tool_choice"] == ("required" if require_finish else "auto")
        assert body["max_completion_tokens"] == 8192
        if expected is None:
            assert "enable_thinking" not in body
        else:
            assert body["enable_thinking"] is expected
    finally:
        asyncio.run(client.aclose())


def test_offline_http_planner_preserves_non_streaming_responses():
    from openai import OpenAI

    from tests.e2e_tests.offline_planner_server import (
        OFFLINE_MODEL_NAME,
        OfflinePlannerServer,
        ScriptedToolCall,
    )

    call = ScriptedToolCall("finish", FINISH_ARGS)
    with OfflinePlannerServer((call,)) as server:
        with OpenAI(base_url=server.base_url, api_key="offline-test") as client:
            response = client.chat.completions.create(
                model=OFFLINE_MODEL_NAME,
                messages=[{"role": "user", "content": "Finish the task."}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "finish",
                            "parameters": common.CommonTools.finish.input_schema,
                        },
                    }
                ],
                stream=False,
            )
        returned = response.choices[0].message.tool_calls[0]
        assert returned.function.name == "finish"
        assert json.loads(returned.function.arguments) == FINISH_ARGS
        server.assert_complete()


def test_api_executes_readonly_calls_concurrently(tmp_path):
    events = Events()
    toolkit = RobotToolkit(events)
    rendezvous = threading.Barrier(2)
    completed = []

    @declare_tool(readonly=True)
    def sense(label: str) -> ToolResult:
        rendezvous.wait(timeout=5)
        completed.append(label)
        return ToolResult(data={"label": label})

    toolkit.add_tool(sense)
    requests = 0

    async def stream(messages, info):
        nonlocal requests
        requests += 1
        if requests == 1:
            yield tool("sense", {"label": "left"}) | tool(
                "sense", {"label": "right"}, 1
            )
        else:
            yield finish()

    result, _, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), toolkit, events
    )
    assert result.error is None
    assert sorted(completed) == ["left", "right"]
    assert result.finish_result == {"_finish": True, **FINISH_ARGS}
    assert result.stats["tool_calls"] == 3


@pytest.mark.parametrize("require_finish", [False, True])
def test_finish_only_text_response_uses_sdk_retry_without_dashboard_wait(
    tmp_path, require_finish
):
    state = dashboard(tmp_path)
    histories = []

    async def stream(messages, info):
        histories.append(copy.deepcopy(messages))
        if len(histories) == 1:
            yield "NEXT=observe; NEED=none"
        else:
            yield finish()

    result, toolkit, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        events=state,
        dashboard_interaction=state,
        require_finish=require_finish,
        timeout_s=1,
    )
    if require_finish:
        assert result.error is None
        assert result.finish_result == {"_finish": True, **FINISH_ARGS}
        assert result.stats["turns_used"] == 2
        assert toolkit.calls == [("finish", FINISH_ARGS)]
        assert any(
            isinstance(part, RetryPromptPart)
            for message in histories[1]
            for part in message.parts
        )
    else:
        assert "planner timed out after 1s" in result.error
        assert result.stats["turns_used"] == 1
        assert result.finish_result is None and toolkit.calls == []


def test_finish_only_repeated_text_preserves_thirty_request_budget(tmp_path):
    requests = 0

    async def stream(messages, info):
        nonlocal requests
        requests += 1
        yield "NEXT=observe; NEED=none"

    result, toolkit, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        require_finish=True,
        max_turns=30,
        timeout_s=600,
    )
    assert result.error is None and result.finish_result is None
    assert result.stats["turns_used"] == requests == 30
    assert toolkit.calls == []


@pytest.mark.parametrize("require_finish", [False, True])
def test_finish_only_keeps_mixed_text_and_real_tool_calls(tmp_path, require_finish):
    requests = 0

    async def stream(messages, info):
        nonlocal requests
        requests += 1
        if requests == 1:
            yield "NEXT=observe; NEED=none"
            yield tool("observe")
        else:
            yield finish()

    result, toolkit, _ = solve(
        tmp_path, FunctionModel(stream_function=stream), require_finish=require_finish
    )
    assert result.error is None and result.finish_result["_finish"]
    assert [name for name, _ in toolkit.calls] == ["observe", "finish"]
    assert result.messages[1]["content"][0]["text"] == "NEXT=observe; NEED=none"


@pytest.mark.parametrize("require_finish", [False, True])
def test_finish_only_keeps_environment_terminal_stop(tmp_path, require_finish):
    events = Events()
    toolkit = RobotToolkit(events)

    def terminal():
        toolkit.planner_stop_result = {"_finish": True, "status": "stopped"}
        return ToolResult(data={"terminated": True})

    toolkit.register("observe", terminal)

    async def stream(messages, info):
        yield tool("observe")

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        events,
        require_finish=require_finish,
    )
    assert result.error is None
    assert result.finish_result == {"_finish": True, "status": "stopped"}
    assert result.stats["turns_used"] == 1
    assert [name for name, _ in toolkit.calls] == ["observe"]


def test_finish_only_rejects_missing_finish_before_model_request(tmp_path):
    events = Events()
    toolkit = RobotToolkit(events)
    toolkit._tools.pop("finish")
    with pytest.raises(ValueError, match="enabled finish tool"):
        solve(tmp_path, TestModel(), toolkit, events, require_finish=True)
    assert toolkit.calls == []


@pytest.mark.parametrize("first_call", ["observe", "blocked"])
def test_tool_availability_refreshes_each_sdk_request(tmp_path, first_call):
    events = Events()
    toolkit = RobotToolkit(events)
    toolkit.planner_tools_only = True
    toolkit.register("blocked", lambda: ToolResult(data={"value": 7}))
    toolkit.planner_tool_available = lambda name: (
        name != "blocked" or any(n == "observe" for n, _ in toolkit.calls)
    )
    seen = []

    async def stream(messages, info):
        names = {t.name for t in info.function_tools}
        seen.append(names)
        if len(seen) == 1:
            assert "blocked" not in names
            yield tool(first_call)
        elif not toolkit.calls:
            assert "blocked" not in names
            yield tool("observe")
        elif not any(n == "blocked" for n, _ in toolkit.calls):
            assert "blocked" in names
            yield tool("blocked")
        else:
            yield finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        events,
        require_finish=True,
    )
    assert result.error is None
    assert [n for n, _ in toolkit.calls] == ["observe", "blocked", "finish"]
    assert result.finish_result == {"_finish": True, **FINISH_ARGS}
    assert len(seen) == (4 if first_call == "blocked" else 3)


def test_availability_dispatch_guard_and_locked_finish(tmp_path):
    from pydantic_ai import ModelRetry

    from rpent.planner.api_loop import _HarnessToolkit

    events = Events()
    toolkit = RobotToolkit(events)
    toolkit.planner_tools_only = True
    toolkit.planner_tool_available = lambda name: name == "finish"
    adapter = _HarnessToolkit(toolkit, dashboard_events=events, no_images=False)
    with pytest.raises(ModelRetry, match="unavailable"):
        asyncio.run(adapter.execute("observe", {}, SimpleNamespace()))
    assert toolkit.calls == []

    async def stream(messages, info):
        assert info.function_tools == []
        yield finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        events,
        require_finish=True,
    )
    assert result.error is None
    assert [n for n, _ in toolkit.calls] == ["finish"]


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("no_images", [False, True])
def test_recent_images_preserve_actual_sdk_history_and_explicit_reread(
    tmp_path, image_state, enabled, no_images
):
    histories = []
    logged = []
    events = Events()
    toolkit = RobotToolkit(events, state=image_state)
    serial = 0

    def observe():
        nonlocal serial
        serial += 1
        return ToolResult(
            data={"observation": serial}, images=[f"image{serial}".encode()]
        )

    toolkit.register("observe", observe)
    toolkit.journal = SimpleNamespace(
        append=lambda kind, payload: (
            logged.append(copy.deepcopy(payload.messages))
            if kind == "model_request"
            else None
        )
    )

    async def stream(messages, info):
        histories.append(copy.deepcopy(messages))
        count = len(histories)
        if count <= 3:
            yield tool("observe")
        elif count == 4:
            yield tool("read_image", {"name": "camera.png", "step": 0})
        else:
            yield finish()

    result, _, _ = solve(
        tmp_path,
        FunctionModel(stream_function=stream),
        toolkit,
        events,
        recent_image_history=enabled,
        no_images=no_images,
        require_finish=True,
    )
    assert result.error is None and result.finish_result["_finish"]
    assert len(histories) == 5 and histories == logged

    def images(messages):
        return [
            item.data
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, (UserPromptPart, ToolReturnPart))
            and isinstance(part.content, (list, tuple))
            for item in part.content
            if isinstance(item, BinaryContent) and item.is_image
        ]

    if no_images:
        assert all(not images(messages) for messages in histories)
    else:
        assert images(histories[2]) == [b"image1", b"image2"]
        assert images(histories[3]) == (
            [b"image2", b"image3"] if enabled else [b"image1", b"image2", b"image3"]
        )
        reread = image_state.load_bytes("camera.png", step=0)
        assert images(histories[4]) == (
            [b"image3", reread]
            if enabled
            else [b"image1", b"image2", b"image3", reread]
        )
    # Text observations and all tool records survive removal of image bytes.
    text = repr(histories[-1])
    for number in range(1, 4):
        assert f'"observation": {number}' in text
    returns = [
        part
        for message in histories[-1]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert [part.tool_name for part in returns] == ["observe"] * 3 + ["read_image"]
    assert bool("Earlier image omitted" in text) is (enabled and not no_images)


def test_recent_images_copy_input_keep_audio_and_request_metadata():
    from pydantic_ai.models import ModelRequestContext, ModelRequestParameters

    from rpent.planner.api_loop import _RecentImageHistory

    audio = BinaryContent(data=b"sound", media_type="audio/wav")
    picture = BinaryContent(data=b"first", media_type="image/png")
    records = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="sense",
                    tool_call_id="first-call",
                    content=["keep text", picture, audio],
                )
            ],
            metadata={"source": "original"},
            run_id="run",
        ),
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=[
                        "middle",
                        BinaryContent(data=b"middle", media_type="image/png"),
                    ]
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="sense",
                    tool_call_id="last-call",
                    content=[BinaryContent(data=b"last", media_type="image/png")],
                )
            ]
        ),
    ]
    original = copy.deepcopy(records)
    context = ModelRequestContext(
        model=TestModel(),
        messages=records,
        model_settings={},
        model_request_parameters=ModelRequestParameters(),
    )
    result = asyncio.run(_RecentImageHistory().before_model_request(None, context))
    assert records == original
    first = result.messages[0]
    assert first.metadata == records[0].metadata and first.run_id == "run"
    assert first.timestamp == records[0].timestamp
    assert first.parts[0].tool_call_id == "first-call"
    assert first.parts[0].content[0] == "keep text"
    assert first.parts[0].content[2] is audio
    assert result.messages[1] is records[1] and result.messages[2] is records[2]
    assert "Earlier image omitted" in first.parts[0].content[1]


@pytest.mark.parametrize("value", [None, 1, "true"])
def test_recent_images_reject_non_boolean(value):
    with pytest.raises(ValueError, match="recent_image_history must be a boolean"):
        ApiAgentLoop(
            model=TestModel(), dashboard_events=Events(), recent_image_history=value
        )


def test_recent_image_history_factory_forwarding(tmp_path, monkeypatch):
    from rpent.planner.base import build_planner

    monkeypatch.setattr("rpent.planner.base.build_api_model", lambda *args: TestModel())
    args = {
        "output_dir": tmp_path,
        "recipe_tag": "test",
        "robot_name": "libero",
        "dashboard_events": Events(),
    }
    assert not build_planner("api", **args).recent_image_history
    assert build_planner(
        "api", api_recent_image_history=True, **args
    ).recent_image_history
    with pytest.raises(ValueError, match="API planner"):
        build_planner("codex", api_recent_image_history=True, **args)
