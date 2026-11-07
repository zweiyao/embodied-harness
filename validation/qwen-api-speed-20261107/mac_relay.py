# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Temporary loopback-only diagnostic relay to the existing Qwen endpoint."""

import http.client
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "llm-mcmnmslm9fd9hzmt.cn-beijing.maas.aliyuncs.com"
PATH = "/compatible-mode/v1/chat/completions"
LOG = Path(__file__).with_name("mac-relay-timing.jsonl")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        started = time.monotonic()
        length = int(self.headers.get("Content-Length", "0"))
        if self.path != PATH or not 0 < length <= 64 * 1024 * 1024:
            self.send_error(400)
            return
        body = self.rfile.read(length)
        received = time.monotonic()
        connection = http.client.HTTPSConnection(HOST, timeout=90)
        record = {
            "bytes": len(body),
            "downstream_upload_s": received - started,
            "upstream_connection": "new_per_request",
        }
        headers_sent = False
        try:
            connection.request(
                "POST",
                PATH,
                body=body,
                headers={
                    "Authorization": self.headers.get("Authorization", ""),
                    "Content-Type": "application/json",
                },
            )
            sent = time.monotonic()
            response = connection.getresponse()
            headers_received = time.monotonic()
            self.send_response(response.status)
            self.send_header(
                "Content-Type", response.getheader("Content-Type", "text/event-stream")
            )
            self.send_header("Connection", "close")
            self.end_headers()
            headers_sent = True
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
            record.update(
                status=response.status,
                upstream_send_s=sent - received,
                upstream_headers_s=headers_received - received,
            )
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            if not headers_sent:
                self.send_error(502, "Upstream connection failed")
            self.close_connection = True
        finally:
            connection.close()
            record["total_s"] = time.monotonic() - started
            with LOG.open("a") as file:
                file.write(json.dumps(record) + "\n")
            self.close_connection = True


HTTPServer(("127.0.0.1", 18090), Handler).serve_forever()
