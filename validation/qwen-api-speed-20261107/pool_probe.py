# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Compare the installed SDK transport's pool lifetime with identical inputs."""

import asyncio
import json
import time
from pathlib import Path

import httpx2
from probe import credentials


async def main():
    root = Path(__file__).parent
    auth = credentials()
    results = []
    for expiry in [5, 60]:
        async with httpx2.AsyncClient(
            trust_env=False,
            limits=httpx2.Limits(keepalive_expiry=expiry),
            timeout=httpx2.Timeout(60, connect=10),
        ) as client:
            for repeat in range(2):
                if repeat:
                    await asyncio.sleep(7)
                payload = json.loads((root / "private-request-18.json").read_text())
                payload.update(stream=True, stream_options={"include_usage": True})
                started = time.monotonic()
                events = []

                async def trace(name, info):
                    events.append({"name": name, "seconds": time.monotonic() - started})

                record = {
                    "keepalive_expiry_s": expiry,
                    "repeat": repeat,
                    "gap_s": 7 if repeat else 0,
                }
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
                (root / "remote-pool-probe.json").write_text(
                    json.dumps(results, indent=2) + "\n"
                )
                print(json.dumps(record), flush=True)


asyncio.run(main())
