# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Join transport attempts to task requests without retaining request contents."""

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/zwy/work/embodied_harness/experiments/qwen-task0-upload-20261111")
OUT = Path("/home/zwy/work/embodied_harness/validation/qwen-task0-upload-20261111")
state = json.loads((ROOT / "status.json").read_text())
assert state["phase"] == "completed", state
rows = json.loads((ROOT / "results.json").read_text())
assert len(rows) == 1
row = rows[0]
run = Path(row["path"])
events = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines()]
requests = [e for e in events if e["kind"] == "model_request"]
responses = [e for e in events if e["kind"] == "model_response"]


def epoch(e):
    return datetime.fromisoformat(e["time"]).timestamp()


def media_types(value):
    if isinstance(value, dict):
        if isinstance(value.get("media_type"), str):
            yield value["media_type"]
        for child in value.values():
            yield from media_types(child)
    elif isinstance(value, list):
        for child in value:
            yield from media_types(child)


transport = defaultdict(list)
for line in (ROOT / "http-trace.jsonl").read_text().splitlines():
    e = json.loads(line)
    transport[e["id"]].append(e)
cohorts = []
probe_attempts = []
for group in transport.values():
    d = {e["event"]: e for e in group}

    def duration(a, b):
        return d[b]["monotonic"] - d[a]["monotonic"] if a in d and b in d else None

    def event(suffix):
        return next((k for k in d if k.endswith(suffix)), None)

    def stage(suffix1, suffix2):
        return duration(event(suffix1), event(suffix2))

    start = group[0]
    i = next(
        (
            i
            for i in range(len(requests) - 1, -1, -1)
            if epoch(requests[i]) <= start["unix"]
        ),
        None,
    )
    a = {
        "id": start["id"],
        "content_length": start["content_length"],
        "start_unix": start["unix"],
        "model_request_index": None if i is None else i + 1,
        "connect_s": stage("connect_tcp.started", "connect_tcp.complete"),
        "tls_s": stage("start_tls.started", "start_tls.complete"),
        "upload_s": stage("send_request_body.started", "send_request_body.complete"),
        "upload_to_headers_s": stage(
            "send_request_body.complete", "receive_response_headers.complete"
        ),
        "http_status": d.get(event("receive_response_headers.complete"), {}).get(
            "status"
        ),
        "failed_stages": [
            {"event": e["event"], "error_type": e.get("error_type")}
            for e in group
            if e["event"].endswith(".failed")
        ],
    }
    if i is None:
        probe_attempts.append(a)
    else:
        cohorts.append(a)
request_rows = []
for i, req in enumerate(requests):
    end = epoch(requests[i + 1]) if i + 1 < len(requests) else float("inf")
    resp = [r for r in responses if epoch(req) <= epoch(r) < end]
    assert len(resp) <= 1
    attempts = [a for a in cohorts if a["model_request_index"] == i + 1]
    images = Counter(media_types(req["payload"]["messages"]))
    assert set(images) <= {"image/png"}
    assert req["payload"]["model_settings"]["extra_body"]["enable_thinking"] is False
    request_rows.append(
        {
            "index": i + 1,
            "image_media_types": dict(images),
            "enable_thinking": False,
            "completed": bool(resp),
            "model_event_span_s": epoch(resp[0]) - epoch(req) if resp else None,
            "http_attempts": len(attempts),
            "content_lengths": [a["content_length"] for a in attempts],
            "upload_sum_s": sum(a["upload_s"] or 0 for a in attempts),
            "upload_to_headers_sum_s": sum(
                a["upload_to_headers_s"] or 0 for a in attempts
            ),
            "usage": resp[0]["payload"].get("usage") if resp else None,
        }
    )


def stats(values):
    return (
        {
            "n": len(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "sum": sum(values),
        }
        if values
        else {"n": 0}
    )


image_attempts = [
    a
    for a in cohorts
    if request_rows[a["model_request_index"] - 1]["image_media_types"]
    and a["upload_s"] is not None
]
completed = [r for r in request_rows if r["completed"]]
report = {
    "diagnostic_only": True,
    "included_in_success_rate_benchmark": False,
    "task": 0,
    "suite": "libero_10_task",
    "seed": 0,
    "instruction": "put both the cream cheese and the tomato sauce in the basket",
    "configuration": json.loads((ROOT / "plan.json").read_text())["config"],
    "outcome": {
        k: row.get(k)
        for k in [
            "classification",
            "evaluation_success",
            "official_success",
            "status",
            "error",
            "elapsed_s",
            "stats",
            "actions",
            "runtime_audit",
        ]
    },
    "model_requests": len(requests),
    "model_responses": len(responses),
    "task_http_attempts": len(cohorts),
    "connect_timeouts": sum(
        any(f["error_type"] == "ConnectTimeout" for f in a["failed_stages"])
        for a in cohorts
    ),
    "image_request_upload_s": stats([a["upload_s"] for a in image_attempts]),
    "image_request_after_upload_to_headers_s": stats(
        [
            a["upload_to_headers_s"]
            for a in image_attempts
            if a["upload_to_headers_s"] is not None
        ]
    ),
    "image_request_bytes": stats([a["content_length"] for a in image_attempts]),
    "model_event_span_s": stats([r["model_event_span_s"] for r in completed]),
    "tool_calls": dict(
        Counter(e["payload"]["name"] for e in events if e["kind"] == "tool_request")
    ),
    "requests": request_rows,
    "attempts": cohorts,
    "preflight_attempts": probe_attempts,
    "cleanup": json.loads((ROOT / "cleanup.json").read_text()),
    "limitations": [
        "send_request_body is the client transport write interval, not proof of server receipt",
        "post-upload-to-headers includes network, queueing and model prefill; not pure thinking",
        "GeneratorExit after logical model completion is stream disposal, not automatically an API failure",
        "image-bearing requests are identified from recorded image/png content; all 30 requests have enable_thinking=false",
        "single diagnostic with a recovered connection timeout; not a matched benchmark or success-rate gain",
    ],
}
(OUT / "upload-summary.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
)
print(
    json.dumps(
        {
            k: v
            for k, v in report.items()
            if k not in ["requests", "attempts", "preflight_attempts", "configuration"]
        },
        ensure_ascii=False,
        indent=2,
    )
)
