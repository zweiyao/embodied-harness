# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Bounded direct HTTPX replay with transport stage timing; no action dispatch."""

import asyncio
import json
import time
from pathlib import Path

import httpx
from probe import credentials


async def main():
    root = Path(__file__).parent
    auth = credentials()
    results = []
    for http2 in [False, True]:
        async with httpx.AsyncClient(
            trust_env=False, http2=http2, timeout=httpx.Timeout(90, connect=10)
        ) as client:
            for repeat in range(2):
                payload = json.loads((root / "private-request-18.json").read_text())
                payload.update(stream=True, stream_options={"include_usage": True})
                started = time.monotonic()
                events = []

                async def trace(name, info):
                    # Never store trace info: it may contain request headers or body.
                    events.append({"name": name, "seconds": time.monotonic() - started})

                record = {"requested_http2": http2, "repeat": repeat}
                first = None
                usage = None
                try:
                    async with client.stream(
                        "POST",
                        auth["url"],
                        json=payload,
                        headers={"Authorization": "Bearer " + auth["key"]},
                        extensions={"trace": trace},
                    ) as response:
                        record.update(
                            status=response.status_code,
                            http_version=response.http_version,
                        )
                        async for line in response.aiter_lines():
                            if (
                                not line.startswith("data:")
                                or line[5:].strip() == "[DONE]"
                            ):
                                continue
                            chunk = json.loads(line[5:])
                            usage = chunk.get("usage") or usage
                            for c in chunk.get("choices", []):
                                d = c.get("delta", {})
                                if first is None and (
                                    d.get("content") or d.get("tool_calls")
                                ):
                                    first = time.monotonic() - started
                    record.update(first_content_s=first, usage=usage)
                except Exception as exc:
                    record["error_type"] = type(exc).__name__
                record.update(total_s=time.monotonic() - started, trace=events)
                results.append(record)
                (root / "remote-transport-trace.json").write_text(
                    json.dumps(results, indent=2) + "\n"
                )
                print(json.dumps(record), flush=True)


asyncio.run(main())
