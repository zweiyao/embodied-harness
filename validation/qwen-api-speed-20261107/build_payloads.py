# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Reconstruct archived provider requests with a mock transport; no API calls."""

import asyncio
import copy
import hashlib
import json
from pathlib import Path

import httpx
from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

ROOT = Path("/home/zwy/work/embodied_harness")
RUN = (
    ROOT
    / "experiments/libero10-task-no-memory-dual-20-20261107/qwen/runs/session/tasks/0005_libero_10_task_t4_s0"
)
OUT = ROOT / "debug/qwen-api-speed-20261107"


def hydrate(value):
    if isinstance(value, dict):
        if set(value) == {"artifact", "bytes"}:
            path = (RUN / value["artifact"]).resolve()
            assert path.is_relative_to(RUN.resolve())
            data = path.read_bytes()
            assert len(data) == value["bytes"]
            return data
        return {k: hydrate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [hydrate(v) for v in value]
    return value


async def main():
    requests = [
        json.loads(line)["payload"]
        for line in (RUN / "events.jsonl").read_text().splitlines()
        if json.loads(line)["kind"] == "model_request"
    ]
    summaries = []
    for index in [0, 4, 18]:
        record = copy.deepcopy(requests[index])
        for name in ["revealed_tool_names", "deferred_capability_ids"]:
            assert record["model_request_parameters"][name] == "set()"
            record["model_request_parameters"][name] = set()
        captured = []

        def capture(request):
            captured.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "mock",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "qwen3.8-flash",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "OK"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as client:
            model = OpenAIChatModel(
                "qwen3.8-flash",
                provider=OpenAIProvider(
                    base_url="https://mock.invalid/v1",
                    api_key="mock",
                    http_client=client,
                ),
            )
            await model.request(
                ModelMessagesTypeAdapter.validate_python(hydrate(record["messages"])),
                record["model_settings"],
                TypeAdapter(ModelRequestParameters).validate_python(
                    record["model_request_parameters"]
                ),
            )
        assert len(captured) == 1
        payload = captured[0]
        payload.pop("stream", None)
        path = OUT / f"private-request-{index}.json"
        path.touch(mode=0o600, exist_ok=True)
        path.write_text(json.dumps(payload))
        serialized = path.read_bytes()
        summaries.append(
            {
                "request_index": index,
                "bytes": len(serialized),
                "sha256": hashlib.sha256(serialized).hexdigest(),
                "messages": len(payload["messages"]),
                "tools": len(payload.get("tools", [])),
                "images": serialized.count(b"data:image/"),
                "enable_thinking": payload.get("enable_thinking"),
                "max_tokens": payload.get(
                    "max_tokens", payload.get("max_completion_tokens")
                ),
            }
        )
    (OUT / "payload-manifest.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


asyncio.run(main())
