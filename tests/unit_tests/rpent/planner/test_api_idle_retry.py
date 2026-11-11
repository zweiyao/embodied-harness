# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Real SDK streams: idle retries never publish abandoned tool calls."""

import asyncio
import json
from functools import partial
from types import SimpleNamespace

import httpx2
import pytest
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from rpent.planner import api_idle_retry
from rpent.planner.api_loop import ApiAgentLoop
from tests.unit_tests.rpent.planner.test_api_contracts import Events, RobotToolkit


def chunk(delta=None, finish=None):
    return (
        "data: "
        + json.dumps(
            {
                "id": "fixture",
                "model": "qwen3.8-flash",
                "created": 1,
                "object": "chat.completion.chunk",
                "choices": [
                    {"index": 0, "delta": delta or {}, "finish_reason": finish}
                ],
            }
        )
        + "\n\n"
    ).encode()


def call(name):
    args = {"status": "success", "summary": "done"} if name == "finish" else {}
    return {
        "tool_calls": [
            {
                "index": 0,
                "id": "call-" + name,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ]
    }


class Stream(httpx2.AsyncByteStream):
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    async def __aiter__(self):
        for delay, data in self.rows:
            await asyncio.sleep(delay)
            yield data

    async def aclose(self):
        self.closed = True


def model_for(handler):
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    model = OpenAIChatModel(
        "qwen3.8-flash", provider=OpenAIProvider(api_key="fixture", http_client=client)
    )
    return model, client


@pytest.fixture
def scaled(monkeypatch):
    real = api_idle_retry.IdleRetryChatModel
    monkeypatch.setattr(
        api_idle_retry,
        "IdleRetryChatModel",
        partial(real, idle_s=0.12, retry_delay_s=0),
    )
    monkeypatch.setattr("rpent.tools.toolkit.substitute", lambda value: value)
    monkeypatch.setattr("rpent.planner.api_loop.substitute", lambda value: value)
    return real


def run(model, *, limit=30):
    events = Events()
    toolkit = RobotToolkit(events)
    toolkit.register("noop", lambda: "done")
    journal = []
    toolkit.journal = SimpleNamespace(
        append=lambda kind, payload: journal.append((kind, payload))
    )
    result = ApiAgentLoop(
        model=model,
        dashboard_events=events,
        idle_retry=True,
        require_finish=True,
        timeout_s=0,
        reasoning_effort="medium",
    ).solve(
        system_prompt="Use tools.",
        user_message="Do task.",
        toolkit=toolkit,
        max_turns=limit,
    )
    return result, toolkit, journal


def test_partial_tool_timeout_retries_same_body_without_duplicate_action(scaled):
    bodies = []
    streams = []

    def handler(request):
        bodies.append(request.content)
        if len(bodies) == 2:
            assert streams[0].closed
        name = "noop" if len(bodies) <= 2 else "finish"
        rows = [(0, chunk(call(name)))]
        rows += (
            [(0.4, chunk())]
            if len(bodies) == 1
            else [(0, chunk(finish="tool_calls")), (0, b"data: [DONE]\n\n")]
        )
        stream = Stream(rows)
        streams.append(stream)
        return httpx2.Response(
            200, headers={"Content-Type": "text/event-stream"}, stream=stream
        )

    model, client = model_for(handler)
    result, toolkit, journal = run(model)
    assert result.error is None and result.finish_result["_finish"]
    assert [name for name, _ in toolkit.calls] == ["noop", "finish"]
    assert result.stats["turns_used"] == 2 and len(bodies) == 3
    assert bodies[0] == bodies[1]
    assert json.loads(bodies[0])["enable_thinking"] is True
    assert json.loads(bodies[0])["tool_choice"] == "auto"
    assert model.client.max_retries == 2
    assert all(s.closed for s in streams)
    assert sum(k == "model_request" for k, _ in journal) == 2
    assert (
        sum(k == "api_transport_attempt" and p["phase"] == "failed" for k, p in journal)
        == 1
    )
    asyncio.run(client.aclose())


def test_continuous_thinking_outlasts_idle_window_and_no_episode_cap(scaled):
    bodies = []

    def handler(request):
        bodies.append(request.content)
        rows = [(0.04, chunk({"reasoning_content": "progress"})) for _ in range(8)]
        rows += [
            (0, chunk(call("finish"))),
            (0, chunk(finish="tool_calls")),
            (0, b"data: [DONE]\n\n"),
        ]
        return httpx2.Response(
            200, headers={"Content-Type": "text/event-stream"}, stream=Stream(rows)
        )

    model, client = model_for(handler)
    result, toolkit, _ = run(model)
    assert result.error is None and result.finish_result["_finish"]
    assert len(bodies) == 1 and result.stats["turns_used"] == 1
    assert len(toolkit.calls) == 1
    asyncio.run(client.aclose())


@pytest.mark.parametrize("failure", ["heartbeat", "eof", "connect"])
def test_two_failed_attempts_stop_as_incident_without_actions(scaled, failure):
    attempts = []
    streams = []

    def handler(request):
        attempts.append(1)
        if failure == "connect":
            raise httpx2.ConnectError("fixture", request=request)
        rows = (
            [(0.03, chunk()) for _ in range(20)]
            if failure == "heartbeat"
            else [(0, chunk(call("noop")))]
        )
        stream = Stream(rows)
        streams.append(stream)
        return httpx2.Response(
            200, headers={"Content-Type": "text/event-stream"}, stream=stream
        )

    model, client = model_for(handler)
    result, toolkit, _ = run(model)
    assert "ModelRetryExhausted" in result.error
    assert len(attempts) == 2 and not toolkit.calls
    assert all(s.closed for s in streams)
    asyncio.run(client.aclose())


def test_authentication_error_not_retried(scaled):
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx2.Response(
            401, json={"error": {"message": "fixture", "type": "authentication_error"}}
        )

    model, client = model_for(handler)
    result, toolkit, _ = run(model)
    assert result.error and len(attempts) == 1 and not toolkit.calls
    asyncio.run(client.aclose())


def test_exactly_30_responses_and_actions(scaled):
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx2.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=Stream(
                [
                    (0, chunk(call("noop"))),
                    (0, chunk(finish="tool_calls")),
                    (0, b"data: [DONE]\n\n"),
                ]
            ),
        )

    model, client = model_for(handler)
    result, toolkit, _ = run(model)
    assert result.error is None and result.finish_result is None
    assert result.stats["turns_used"] == 30 and len(attempts) == 30
    assert len(toolkit.calls) == 30
    asyncio.run(client.aclose())


def test_external_cancel_closes_stream_without_retry():
    async def check():
        attempts = []
        stream = Stream([(1, chunk(call("noop")))])

        def handler(request):
            attempts.append(1)
            return httpx2.Response(
                200, headers={"Content-Type": "text/event-stream"}, stream=stream
            )

        model, client = model_for(handler)
        retry = api_idle_retry.IdleRetryChatModel(model, idle_s=10)
        task = asyncio.create_task(
            retry._completions_create([], True, {}, ModelRequestParameters())
        )
        await asyncio.sleep(0.04)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed and len(attempts) == 1
        await client.aclose()

    asyncio.run(check())


@pytest.mark.parametrize("finish_after_text", [True, False])
def test_thinking_auto_tool_choice_keeps_local_finish_gate(scaled, finish_after_text):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert body["enable_thinking"] is True and body["tool_choice"] == "auto"
        should_finish = finish_after_text and len(bodies) == 2
        delta = call("finish") if should_finish else {"content": "The task is done."}
        reason = "tool_calls" if should_finish else "stop"
        return httpx2.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=Stream(
                [(0, chunk(delta)), (0, chunk(finish=reason)), (0, b"data: [DONE]\n\n")]
            ),
        )

    model, client = model_for(handler)
    result, toolkit, _ = run(model)
    assert result.error is None
    if finish_after_text:
        assert result.finish_result["_finish"] and len(bodies) == 2
        assert [name for name, _ in toolkit.calls] == ["finish"]
    else:
        assert result.finish_result is None and len(bodies) == 30
        assert result.stats["turns_used"] == 30 and not toolkit.calls
    asyncio.run(client.aclose())
