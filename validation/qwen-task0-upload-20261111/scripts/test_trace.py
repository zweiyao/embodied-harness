# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Exercise real HTTPX2 serialization, timing and failed-body propagation offline."""

import asyncio
import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2
from trace_workbench import install

seen = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        expected = int(self.headers["Content-Length"])
        data = self.rfile.read(expected)
        if len(data) != expected:
            return  # Expected client cancellation in the failure test.
        seen.append(data)
        time.sleep(0.1)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "trace.jsonl"
        install(p)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/chat/completions"
        body = b"PRIVATE_TEST_PAYLOAD" * 1000
        prior = []

        async def callback(event, info):
            prior.append(event)

        async with httpx2.AsyncClient() as client:
            r = await client.post(
                url,
                content=body,
                headers={"Authorization": "Bearer PRIVATE_TOKEN"},
                extensions={"trace": callback},
            )
            assert r.status_code == 200
            assert seen == [body]

            async def cancelled_body():
                raise asyncio.CancelledError()
                yield b""

            try:
                await client.post(
                    url, content=cancelled_body(), headers={"Content-Length": "10"}
                )
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("Cancellation swallowed")
        server.shutdown()
        text = p.read_text()
        rows = [json.loads(x) for x in text.splitlines()]
        assert "PRIVATE_TOKEN" not in text and "PRIVATE_TEST_PAYLOAD" not in text
        success = rows[0]["id"]
        events = {r["event"]: r for r in rows if r["id"] == success}
        upload = (
            events["http11.send_request_body.complete"]["monotonic"]
            - events["http11.send_request_body.started"]["monotonic"]
        )
        wait = (
            events["http11.receive_response_headers.complete"]["monotonic"]
            - events["http11.send_request_body.complete"]["monotonic"]
        )
        assert upload >= 0 and wait >= 0.09
        assert any(
            r.get("error_type") == "CancelledError"
            and r["event"] == "http11.send_request_body.failed"
            for r in rows
        )
        assert any(x == "http11.send_request_body.complete" for x in prior)
        assert events["request.started"]["content_length"] == len(body)
        print(
            json.dumps(
                {
                    "passed": True,
                    "request_body_unchanged": True,
                    "prior_trace_preserved": True,
                    "cancellation_propagated": True,
                    "secrets_and_payload_excluded": True,
                    "upload_s": upload,
                    "server_wait_s": wait,
                }
            )
        )


asyncio.run(main())
