# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""One preauthorized reverse-order pair after the inconclusive initial pair."""

import asyncio
import json
import os

from diagnose import PROXY_KEYS, ROOT, one, prepared, save


async def main():
    initial = json.loads((ROOT / "results.json").read_text())
    summary = json.loads((ROOT / "summary.json").read_text())
    assert len(initial) == 2 and not summary["clear_directional_difference"]
    assert not (ROOT / "reverse-results.json").exists()
    assert json.loads((ROOT / "reverse-pair-decision.json").read_text())["authorized"]
    for key in PROXY_KEYS:
        os.environ.pop(key, None)
    profile, body, metadata = prepared()
    prior = json.loads((ROOT / "metadata.json").read_text())
    assert metadata["body_sha256"] == prior["body_sha256"]
    assert metadata["images"] == prior["images"]
    records = []
    for family in ("IPv4", "IPv6"):
        save(
            "reverse-status.json",
            {
                "phase": "running",
                "current": family,
                "completed": len(records),
                "planned": 2,
            },
        )
        record = await one(family, profile, body, metadata["body_sha256"])
        records.append(record)
        save("reverse-results.json", records)
        print(
            json.dumps(
                {
                    k: record.get(k)
                    for k in (
                        "family_requested",
                        "expected_peer_family_verified",
                        "total_s",
                        "http_status",
                        "send_body_complete_s",
                        "response_headers_s",
                        "exception_type",
                        "usage",
                    )
                }
            ),
            flush=True,
        )
    save("all-results.json", initial + records)
    save(
        "reverse-status.json",
        {"phase": "completed", "completed": 2, "planned": 2, "total_model_requests": 4},
    )


if __name__ == "__main__":
    asyncio.run(main())
