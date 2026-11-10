# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Bounded direct address-family API diagnostic; no simulator or harness edits."""

import argparse
import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BATCH = ROOT.parent / "iteration-05"
PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def save(name, value):
    path = ROOT / name
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def prepared():
    assert json.loads((BATCH / "status.json").read_text())["phase"] == "completed"
    assert json.loads((BATCH / "cleanup.json").read_text())["passed"]
    assert json.loads((BATCH / "final-verification.json").read_text())["passed"]
    plan = json.loads((BATCH / "plan.json").read_text())
    config = json.loads((BATCH / "a/workbench.json").read_text())
    profile = next(
        p for p in config["models"] if p["id"] == plan["config"]["model_profile"]
    )
    run = next((BATCH / "a/runs/session/tasks").iterdir())
    events = [json.loads(s) for s in (run / "events.jsonl").read_text().splitlines()]
    request = [r for r in events if r["kind"] == "model_request"][1]
    binaries = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("kind") == "binary":
                binaries.append(value)
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(request["payload"])
    assert len(binaries) == 3
    content = [{"type": "text", "text": "Reply only OK."}]
    images = []
    for binary in binaries:
        artifact = (run / binary["data"]["artifact"]).resolve()
        assert artifact.is_relative_to(run.resolve())
        raw = artifact.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert digest == artifact.stem and len(raw) == binary["data"]["bytes"]
        assert binary["media_type"] == "image/png"
        images.append({"sha256": digest, "bytes": len(raw), "media_type": "image/png"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(raw).decode()
                },
            }
        )
    model = profile["model"].removeprefix("openai-chat:")
    assert model == "qwen3.8-flash"
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 16,
            "enable_thinking": False,
            "stream": False,
        },
        separators=(",", ":"),
    ).encode()
    metadata = {
        "source_run": str(run),
        "source_model_request": 2,
        "images": images,
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_bytes": len(body),
        "model": model,
        "max_tokens": 16,
        "thinking_enabled": False,
        "TLS_verified": True,
        "transport_retries": 0,
        "overall_timeout_s": 180,
        "trust_env": False,
        "family_order": ["IPv6", "IPv4"],
        "source_batch_terminal_audit_cleanup_passed": True,
    }
    return profile, body, metadata


async def one(family, profile, body, body_digest):
    started = time.monotonic()
    record = {
        "family_requested": family,
        "started_at": datetime.now(UTC).isoformat(),
        "body_sha256": body_digest,
        "body_bytes": len(body),
        "events": [],
        "actual_peer_families": [],
    }

    async def trace(name, info):
        # Never serialize arbitrary trace info: it may contain headers or payloads.
        record["events"].append(
            {"event": name, "elapsed_s": time.monotonic() - started}
        )
        stream = info.get("return_value")
        if stream is not None and name in (
            "connection.connect_tcp.complete",
            "connection.start_tls.complete",
        ):
            peer = stream.get_extra_info("server_addr")
            if peer:
                actual = "IPv" + str(ipaddress.ip_address(peer[0]).version)
                if actual not in record["actual_peer_families"]:
                    record["actual_peer_families"].append(actual)

    transport = httpx.AsyncHTTPTransport(
        local_address="::" if family == "IPv6" else "0.0.0.0",
        retries=0,
        trust_env=False,
        verify=True,
        http2=False,
    )
    key = Path(profile["key_file"]).read_text().strip()
    endpoint = profile["base_url"].rstrip("/") + "/chat/completions"
    assert endpoint.startswith("https://")
    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=180, trust_env=False, follow_redirects=False
        ) as client:
            response = await asyncio.wait_for(
                client.post(
                    endpoint,
                    content=body,
                    headers={
                        "Authorization": "Bearer " + key,
                        "Content-Type": "application/json",
                    },
                    extensions={"trace": trace},
                ),
                timeout=180,
            )
            record["http_status"] = response.status_code
            if response.status_code == 200:
                result = response.json()
                record["usage"] = result.get("usage")
                record["model"] = result.get("model")
                choice = result["choices"][0]
                record["finish_reason"] = choice.get("finish_reason")
                record["response_equals_OK"] = (
                    isinstance(choice["message"].get("content"), str)
                    and choice["message"]["content"].strip() == "OK"
                )
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        record["exception_type"] = type(exc).__name__
    record["total_s"] = time.monotonic() - started
    record["expected_peer_family_verified"] = record["actual_peer_families"] == [family]
    for key, event in (
        ("send_body_start_s", "http11.send_request_body.started"),
        ("send_body_complete_s", "http11.send_request_body.complete"),
        ("response_headers_s", "http11.receive_response_headers.complete"),
    ):
        times = [e["elapsed_s"] for e in record["events"] if e["event"] == event]
        record[key] = times[0] if times else None
    return record


async def main(check_only):
    for key in PROXY_KEYS:
        os.environ.pop(key, None)
    profile, body, metadata = prepared()
    metadata["six_proxy_variables_absent"] = all(
        key not in os.environ for key in PROXY_KEYS
    )
    if check_only:
        save("preflight.json", {"passed": True, **metadata, "model_requests": 0})
        print(
            json.dumps(
                {
                    "passed": True,
                    "body_bytes": len(body),
                    "images": 3,
                    "model_requests": 0,
                }
            )
        )
        return
    assert not (ROOT / "results.json").exists(), (
        "Preserve completed or partial diagnostic attempts"
    )
    save("metadata.json", metadata)
    records = []
    for family in ("IPv6", "IPv4"):
        save(
            "status.json",
            {
                "phase": "running",
                "current": family,
                "completed": len(records),
                "planned": 2,
            },
        )
        record = await one(family, profile, body, metadata["body_sha256"])
        records.append(record)
        save("results.json", records)
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
    successful = all(
        r.get("http_status") == 200 and r["expected_peer_family_verified"]
        for r in records
    )
    ratio = max(r["total_s"] for r in records) / min(r["total_s"] for r in records)
    delta = max(r["total_s"] for r in records) - min(r["total_s"] for r in records)
    save(
        "summary.json",
        {
            "model_requests": 2,
            "successful_pair": successful,
            "clear_directional_difference": successful and ratio >= 3 and delta >= 10,
            "larger_to_smaller_total_ratio": ratio,
            "total_difference_s": delta,
            "limitation": "Two sequential requests, same image bytes, different IP families/endpoints; diagnostic only, not task-success evidence. Client send completion is not remote ACK. Any second pair requires a separately recorded ambiguity decision.",
        },
    )
    save("status.json", {"phase": "completed", "completed": 2, "planned": 2})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.check_only))
