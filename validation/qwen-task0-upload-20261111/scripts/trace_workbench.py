# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Record HTTP stage timings without changing transport or request content."""

import json
import os
import runpy
import sys
import time
import uuid
from pathlib import Path

import httpcore2


def install(path):
    original = httpcore2.AsyncConnectionPool.handle_async_request

    def emit(request_id, event, **fields):
        row = dict(
            id=request_id,
            event=event,
            monotonic=time.monotonic(),
            unix=time.time(),
            pid=os.getpid(),
            **fields,
        )
        with path.open("a") as file:
            file.write(json.dumps(row) + "\n")

    async def measured(pool, request):
        if request.method != b"POST" or not request.url.target.split(b"?")[0].endswith(
            b"/chat/completions"
        ):
            return await original(pool, request)
        request_id = uuid.uuid4().hex
        length = next(
            (int(v) for k, v in request.headers if k.lower() == b"content-length"), None
        )
        emit(request_id, "request.started", content_length=length)
        prior = request.extensions.get("trace")

        async def trace(event, info):
            fields = {}
            if "exception" in info:
                fields["error_type"] = type(info["exception"]).__name__
            if event.endswith("receive_response_headers.complete"):
                fields["status"] = info["return_value"][1]
            emit(request_id, event, **fields)
            if prior is not None:
                await prior(event, info)

        request.extensions["trace"] = trace
        try:
            response = await original(pool, request)
            emit(request_id, "response.headers_returned", status=response.status)
            return response
        except BaseException as exc:
            emit(request_id, "request.failed", error_type=type(exc).__name__)
            raise

    httpcore2.AsyncConnectionPool.handle_async_request = measured


if __name__ == "__main__":
    output = Path(sys.argv[1])
    install(output)
    sys.argv = ["rpent.cli.main", *sys.argv[2:]]
    runpy.run_module("rpent.cli.main", run_name="__main__")
