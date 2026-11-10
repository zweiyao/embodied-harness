# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Offline SDK output-contract probe; no RPent/env imports or network transport."""

import asyncio
import json
from importlib.metadata import version
from pathlib import Path

import httpx
from pydantic_ai import Agent, ToolOutput, UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

ROOT = Path(__file__).resolve().parent
LABEL = "NEXT=observe; NEED=none"


def completion(text=None, tool=None):
    message = {"role": "assistant", "content": text}
    if tool:
        message["tool_calls"] = [
            {
                "id": "offline-call",
                "type": "function",
                "function": {
                    "name": tool,
                    "arguments": json.dumps({"status": "stuck", "summary": "fixture"})
                    if tool == "finish"
                    else "{}",
                },
            }
        ]
    return {
        "id": "offline-completion",
        "object": "chat.completion",
        "created": 0,
        "model": "qwen3.8-flash",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool else "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


async def case(name, *, require_finish, replies, request_limit=3):
    bodies, handlers = [], []

    def transport(request):
        assert request.url.host == "offline.invalid"
        assert request.headers["authorization"] == "Bearer offline-placeholder"
        body = json.loads(request.content)
        assert not body.get("stream")
        bodies.append(body)
        assert len(bodies) <= len(replies), "Unexpected extra offline request"
        return httpx.Response(200, json=replies[len(bodies) - 1])

    def finish(status: str, summary: str) -> dict:
        handlers.append("finish")
        return {"_finish": True, "status": status, "summary": summary}

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport), trust_env=False
    ) as client:
        model = OpenAIChatModel(
            "qwen3.8-flash",
            provider=OpenAIProvider(
                base_url="https://offline.invalid/v1",
                api_key="offline-placeholder",
                http_client=client,
            ),
        )
        outputs = [ToolOutput(finish, name="finish")]
        if not require_finish:
            outputs.insert(0, str)
        agent = Agent(
            model,
            output_type=outputs,
            end_strategy="early",
            retries={"output": request_limit},
            model_settings={
                "max_tokens": 16384,
                "parallel_tool_calls": True,
                "extra_body": {"enable_thinking": False},
            },
        )
        agent.instrument = False

        @agent.tool_plain
        def observe() -> dict:
            handlers.append("observe")
            return {"fixture_observation": True}

        result, error = None, None
        try:
            result = await agent.run(
                "Offline contract fixture.",
                usage_limits=UsageLimits(request_limit=request_limit),
            )
        except UsageLimitExceeded:
            error = "UsageLimitExceeded"
    expected_choice = "required" if require_finish else "auto"
    assert all(body["tool_choice"] == expected_choice for body in bodies)
    assert all(
        {item["function"]["name"] for item in body["tools"]} == {"observe", "finish"}
        for body in bodies
    )
    assert all(body["enable_thinking"] is False for body in bodies)
    if name == "default_text_final":
        assert len(bodies) == 1 and result.output == LABEL and handlers == []
    elif name == "required_text_retries_then_finish":
        assert len(bodies) == 2 and result.output["_finish"] and handlers == ["finish"]
        assert "Please include your response in a tool call." in json.dumps(
            bodies[1]["messages"]
        )
    elif name == "required_mixed_text_and_tool":
        assert len(bodies) == 2 and handlers == ["observe", "finish"]
        assert LABEL in json.dumps(bodies[1]["messages"])
    elif name == "required_repeated_text_budget":
        assert (
            error == "UsageLimitExceeded"
            and len(bodies) == request_limit
            and handlers == []
        )
    return {
        "case": name,
        "passed": True,
        "wire_tool_choice": expected_choice,
        "mock_http_requests": len(bodies),
        "fixture_handlers": handlers,
        "error": error,
    }


async def main():
    rows = []
    for name, enabled, replies in [
        ("default_text_final", False, [completion(LABEL)]),
        (
            "required_text_retries_then_finish",
            True,
            [completion(LABEL), completion(tool="finish")],
        ),
        (
            "required_mixed_text_and_tool",
            True,
            [completion(LABEL, "observe"), completion(tool="finish")],
        ),
        ("required_repeated_text_budget", True, [completion(LABEL)] * 3),
    ]:
        rows.append(await case(name, require_finish=enabled, replies=replies))
    report = {
        "passed": True,
        "pydantic_ai_slim_version": version("pydantic-ai-slim"),
        "cases": rows,
        "external_model_requests": 0,
        "simulator_actions": 0,
        "scope": "SDK-only mocked transport. Does not validate RPent configuration, streaming, timeout/cancel, or task efficacy.",
    }
    (ROOT / "independent-sdk-probe.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(main())
