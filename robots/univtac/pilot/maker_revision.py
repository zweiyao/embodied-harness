# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""One paired refinement per maker branch, with immutable consumer evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import time
from pathlib import Path

from jsonschema import Draft202012Validator

from robots.libero.research.library import validate_tools
from robots.univtac.pilot import Pilot, _file_refs, _verify_refs, digest, maker
from robots.univtac.pilot.evidence import _scrub
from rpent.dashboard.workbench import clean

SYSTEM = maker.SYSTEM.replace(
    "The initial code is an empty run skeleton, not a prior candidate. No evaluation outcome is supplied.",
    "This is paired refinement: each branch receives its own previous candidate, not an identical "
    "candidate starting point. The empty base_source is retained only as the original common-input "
    "record. Review the prior candidate using the supplied evidence. Retain, revise or replace it "
    "only when warranted; do not force a particular tool or force adoption. No evaluation outcome "
    "is supplied. Consumer messages are model claims, not verified geometry or success. Returned "
    "thinking is only what the service provided. A length-limited response is incomplete. "
    "Tool calls are observations or unexecuted proposals as recorded, not task outcomes. "
    "Both branches also receive identical shared_observed_measurements: native perceptual "
    "values queried by Qwen Max, without acquisition order, model reasoning or errors. "
    "This is a shared second-stage supplement; query parameters still reveal selection cues. "
    "Its image hashes identify recorded images, not additional visible pixels.",
)
PART_FIELDS = ("part_kind", "content", "tool_name", "args", "tool_call_id")
PARTS = {"thinking", "text", "tool-call", "tool-return"}


def _json(path):
    return json.loads(Path(path).read_text())


def _save(root, prefix, value):
    path = root / f"{prefix}-{digest(value)}.json"
    if path.exists():
        if _json(path) != value:
            raise ValueError("Immutable revision artifact changed")
    else:
        maker._write(path, value)
    return _file_refs({"file": path})["file"]


def _read(ref):
    _verify_refs({"revision": ref}, label="maker revision")
    return _json(ref["path"])


def _result(events, request_id):
    result = next(
        (
            e["result"]
            for e in events
            if e["kind"] == "offline_result" and e["id"] == request_id
        ),
        None,
    )
    if result is None:
        raise ValueError("Offline source request must have a recorded result")
    return result


def verified_maker_result(pilot: Pilot, events: list[dict], call: dict) -> dict:
    """Verify the candidate and branch usage through this request, not later calls."""
    result = _result(events, call["id"])
    if (
        result.get("status") != "completed"
        or result.get("budget_check") != "passed_posthoc"
    ):
        raise ValueError("Latest maker must complete and pass its output budget")
    branch = [
        e
        for e in events
        if e["kind"] == "offline"
        and e["purpose"] == "maker"
        and e["variant"] == call["variant"]
    ]
    branch = branch[
        : next(
            index + 1 for index, item in enumerate(branch) if item["id"] == call["id"]
        )
    ]
    total = 0
    for item in branch:
        tokens = maker._output_tokens(_result(events, item["id"]).get("usage", {}))
        if type(tokens) is not int or tokens < 0 or tokens > item["max_tokens"]:
            raise ValueError(
                "Recorded maker output usage is missing or exceeds its limit"
            )
        total += tokens
    if total > call["maker_budget"]["max_tokens"]:
        raise ValueError("Recorded maker branch output budget exceeded")
    directory = (pilot.root / "maker" / call["id"]).resolve()
    if Path(result.get("artifact_dir", "")).resolve() != directory:
        raise ValueError("Maker result must reference its own artifact directory")
    candidate = _json(directory / "candidate.json")
    validate_tools([candidate])
    if digest(candidate) != result.get("candidate_sha256"):
        raise ValueError("Maker candidate source hash mismatch")
    if call.get("revision"):
        if result.get("revision") != call["revision"] or _json(
            directory / "request.json"
        ) != _read(call["revision"]["request"]):
            raise ValueError("Recorded maker request differs from its revision binding")
    return candidate


def _compact(value, directory, images):
    if isinstance(value, dict):
        if set(value) == {"artifact", "bytes"}:
            name = value["artifact"]
            if not re.fullmatch(r"inputs/[0-9a-f]{64}\.bin", name):
                raise ValueError(
                    "Feedback image must be a recorded sensor-image reference"
                )
            ref = _file_refs({"image": directory / name})["image"]
            if (
                ref["sha256"] != Path(name).stem
                or Path(ref["path"]).stat().st_size != value["bytes"]
            ):
                raise ValueError("Feedback image bytes changed")
            images[ref["sha256"]] = ref
            return {"image_sha256": ref["sha256"], "bytes": value["bytes"]}
        return {
            key: _compact(child, directory, images)
            for key, child in _scrub(value).items()
        }
    if isinstance(value, list):
        return [_compact(child, directory, images) for child in value]
    if isinstance(value, str) and "data:image/" in value:
        raise ValueError("Inline image data is not allowed in feedback text")
    return clean(value)


def _parts(parts, directory, images):
    return [
        _compact(
            {key: part[key] for key in PART_FIELDS if key in part}, directory, images
        )
        for part in parts
        if part.get("part_kind") in PARTS
    ]


def _verify_wire(request, wire):
    """Match the recorded Max continuation to its ledger-bound OpenAI wire."""
    messages = wire.get("messages", [])
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    returns = [
        p
        for m in request
        for p in m.get("parts", [])
        if p.get("part_kind") == "tool-return"
    ]
    if len(tool_messages) != len(returns):
        raise ValueError("Recorded tool returns differ from the bound wire")
    for returned in returns:
        matched = [
            m
            for m in tool_messages
            if m.get("tool_call_id") == returned["tool_call_id"]
        ]
        if len(matched) != 1 or not isinstance(returned["content"], list):
            raise ValueError("Recorded tool return format differs from the bound wire")
        expected = []
        for part in returned["content"]:
            if isinstance(part, dict) and part.get("kind") == "binary":
                identifier = part["identifier"]
                expected.append(f"See file {identifier}.")
                tag = f'<tool_result tool_name="{returned["tool_name"]}" tool_call_id="{returned["tool_call_id"]}" file_id="{identifier}">'
                urls = []
                for message in messages:
                    parts = message.get("content")
                    if message.get("role") != "user" or not isinstance(parts, list):
                        continue
                    for index, block in enumerate(parts[:-1]):
                        if block.get("text") == tag:
                            urls.append(
                                parts[index + 1].get("image_url", {}).get("url", "")
                            )
                prefix = f"data:{part['media_type']};base64,"
                if (
                    len(urls) != 1
                    or not urls[0].startswith(prefix)
                    or hashlib.sha256(
                        base64.b64decode(urls[0][len(prefix) :], validate=True)
                    ).hexdigest()
                    != Path(part["data"]["artifact"]).stem
                ):
                    raise ValueError(
                        "Recorded result image differs from the bound wire"
                    )
            else:
                expected.append(part)
        if json.loads(matched[0]["content"]) != expected:
            raise ValueError("Recorded tool return content differs from the bound wire")
    for message in request:
        if message.get("kind") != "response":
            continue
        parts = message["parts"]
        calls = [p for p in parts if p.get("part_kind") == "tool-call"]
        ids = [p["tool_call_id"] for p in calls]
        assistants = [
            m
            for m in messages
            if m.get("role") == "assistant"
            and [c["id"] for c in m.get("tool_calls", [])] == ids
        ]
        if len(assistants) != 1:
            raise ValueError("Recorded first response differs from the bound wire")
        assistant = assistants[0]
        for key, kind in (("content", "text"), ("reasoning_content", "thinking")):
            if (assistant.get(key) or "") != "".join(
                p["content"] for p in parts if p.get("part_kind") == kind
            ):
                raise ValueError(
                    "Recorded first response text differs from the bound wire"
                )
        for call, sent in zip(calls, assistant["tool_calls"], strict=True):
            args = (
                call["args"]
                if isinstance(call["args"], dict)
                else json.loads(call["args"])
            )
            if call["tool_name"] != sent["function"]["name"] or args != json.loads(
                sent["function"]["arguments"]
            ):
                raise ValueError(
                    "Recorded first response arguments differ from the bound wire"
                )


def feedback(
    pilot: Pilot, events: list[dict], windows: list[dict], candidate: dict
) -> dict:
    """Read only two development dialogs and their explicit sensor-image refs.

    Each window names its source attempt and first/after request directories.
    No review, evaluator, outcome or arbitrary artifact is read.
    """
    if len(windows) != 2 or len({w["attempt_id"] for w in windows}) != 2:
        raise ValueError("Provide the two distinct development feedback windows")
    output, sources, images = [], {}, {}
    for window in windows:
        if set(window) != {"attempt_id", "first", "after"}:
            raise ValueError("Feedback window needs attempt_id/first/after only")
        inputs = pilot._maker_inputs(events, "G1", [window["attempt_id"]])
        cell = pilot._cell(pilot._attempt(events, window["attempt_id"])["cell"])
        if cell["id"] not in {"dev-03", "dev-04"}:
            raise ValueError(
                "Feedback is restricted to the two GPT development windows"
            )
        rows, first_parts = [], None
        for stage, purpose in (
            ("first", "tool_acceptance"),
            ("after", "after_native_observation"),
        ):
            directory = Path(window[stage]).resolve()
            refs = _file_refs(
                {
                    name: directory / f"{name}.json"
                    for name in ("request", "request-wire", "response", "result")
                }
            )
            result = _read(refs["result"])
            call = next(
                (
                    e
                    for e in events
                    if e["kind"] == "offline" and e["id"] == result["request_id"]
                ),
                {},
            )
            if (call.get("purpose"), call.get("variant"), call.get("inputs_hash")) != (
                purpose,
                "G1",
                digest(inputs),
            ):
                raise ValueError(
                    "Feedback request purpose or development source differs"
                )
            if (
                result != _result(events, call["id"])
                or result.get("status") != "completed"
            ):
                raise ValueError(
                    "Feedback response must match a completed ledger result"
                )
            if result.get("actions_executed") != 0:
                raise ValueError("Offline feedback must contain no executed actions")
            if refs["request-wire"]["sha256"] != result.get("wire_sha256"):
                raise ValueError("Feedback wire hash differs from recorded request")
            wire = _read(refs["request-wire"])
            declarations = [
                {
                    key: item["function"].get(key)
                    for key in ("name", "description", "parameters")
                }
                for item in wire.get("tools", [])
                if item.get("type") == "function"
            ]
            declaration = {
                key: candidate[key] for key in ("name", "description", "parameters")
            }
            if wire.get("model") != "qwen3.8-max" or declaration not in declarations:
                raise ValueError(
                    "Feedback must expose the original G1 candidate to Qwen Max"
                )
            request = _read(refs["request"])
            response = _read(refs["response"])
            _verify_wire(request, wire)
            public = _parts(response.get("parts", []), directory, images)
            returns = [
                part
                for message in request
                for part in _parts(message.get("parts", []), directory, images)
                if part["part_kind"] == "tool-return"
            ]
            if stage == "first":
                first_parts = public
                if returns:
                    raise ValueError(
                        "First feedback response must precede tool returns"
                    )
            else:
                previous = [
                    _parts(m.get("parts", []), directory, images)
                    for m in request
                    if m.get("kind") == "response"
                ]
                ids = {
                    p["tool_call_id"]
                    for p in first_parts
                    if p["part_kind"] == "tool-call"
                }
                if (
                    first_parts not in previous
                    or not ids
                    or len(ids)
                    != sum(p["part_kind"] == "tool-call" for p in first_parts)
                    or len(returns) != len(ids)
                    or {p["tool_call_id"] for p in returns} != ids
                ):
                    raise ValueError(
                        "Follow-up must include the first response and all tool returns"
                    )
                names = {
                    p["tool_call_id"]: p["tool_name"]
                    for p in first_parts
                    if p["part_kind"] == "tool-call"
                }
                if any(p["tool_name"] != names[p["tool_call_id"]] for p in returns):
                    raise ValueError(
                        "Tool return names must match their original calls"
                    )
            sources[call["id"]] = refs
            rows.append(
                {
                    "request_id": call["id"],
                    "stage": stage,
                    "tool_results_seen_by_model": stage == "after",
                    "preceding_tool_returns": returns,
                    "returned_parts": public,
                    "finish_reason": response.get("finish_reason"),
                    "usage": result.get("usage"),
                    "elapsed_s": result.get("total_s"),
                    "actions_executed": 0,
                }
            )
        output.append(
            {
                "attempt_id": window["attempt_id"],
                "available_tools": declarations,
                "responses": rows,
            }
        )
    return {
        "schema_version": 1,
        "windows": output,
        "source_refs": sources,
        "image_refs": images,
    }


def shared_measurements(exported: dict) -> dict:
    """Equalize extra measured values without forwarding acquisition dialogs."""
    rows = {}
    for window in exported["windows"]:
        first, after = window["responses"]
        calls = {
            p["tool_call_id"]: p
            for p in first["returned_parts"]
            if p["part_kind"] == "tool-call"
        }
        for returned in after["preceding_tool_returns"]:
            call = calls[returned["tool_call_id"]]
            if call["tool_name"] not in {
                "observe",
                "read_image",
                "tactile_stats",
                "depth_points",
            }:
                continue
            content = returned.get("content")
            parts = content if isinstance(content, list) else [content]
            values, images = [], []
            for part in parts:
                if isinstance(part, str):
                    try:
                        value = json.loads(part)
                    except ValueError:
                        continue  # Labels and errors stay only in G1's actual dialog.
                    if isinstance(value, dict):
                        values.append(value)
                elif isinstance(part, dict) and part.get("kind") == "binary":
                    images.append(
                        {
                            "sha256": part["data"]["image_sha256"],
                            "media_type": part["media_type"],
                        }
                    )
            # Keep only native structured measurements with their recorded frame.
            # Do not infer a step from request order or an unexecuted proposal.
            for value in values:
                if type(value.get("step")) is not int or _has_error(value):
                    continue
                args = call.get("args", {})
                if isinstance(args, str):
                    args = json.loads(args)
                row = {
                    "attempt_id": window["attempt_id"],
                    "tool_name": call["tool_name"],
                    "arguments": args,
                    "result": _scrub(value),
                    "images": sorted(images, key=lambda image: image["sha256"]),
                }
                rows[digest(row)] = row
    if not rows:
        raise ValueError(
            "Feedback contains no successful native measurements with recorded frames"
        )
    return {
        "schema_version": 1,
        "source": "Native perception queried by Qwen Max during development; shared second-stage supplement. Query parameters retain selection cues. Image hashes are references, not added pixels.",
        "measurements": [rows[key] for key in sorted(rows)],
    }


def _has_error(value):
    if isinstance(value, dict):
        return bool(value.get("error")) or any(
            _has_error(child) for child in value.values()
        )
    return isinstance(value, list) and any(_has_error(child) for child in value)


def _settings():
    return {
        "system": SYSTEM,
        "model": maker.MODEL,
        "reasoning_effort": "low",
        "timeout_s": 180,
        "output_schema": maker.OUTPUT_SCHEMA,
        "maker_budget": maker.BUDGET,
        "per_call_tokens": maker.PER_CALL_TOKENS,
        "sdk_version": maker.version("openai-codex"),
        "driver_sha256": {
            name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for name, path in (
                ("revision", __file__),
                ("maker", maker.__file__),
                ("codex_sdk", maker.codex_sdk.__file__),
            )
        },
    }


def _materialize(pilot, events, contract, variant, inputs):
    if (
        set(contract)
        != {
            "schema_version",
            "kind",
            "parent_contract",
            "settings",
            "parents",
            "feedback_windows",
            "feedback",
        }
        or contract["schema_version"] != 2
        or contract["kind"] != "paired_refinement"
        or contract["settings"] != _settings()
    ):
        raise ValueError("Paired refinement contract or driver differs")
    parent = _read(contract["parent_contract"])
    if (
        Path(contract["parent_contract"]["path"]).resolve()
        != (pilot.root / "maker-common.json").resolve()
    ):
        raise ValueError("Revision must retain the original common contract")
    expected = {
        "model": maker.MODEL,
        "reasoning_effort": "low",
        "timeout_s": 180,
        "maker_budget": maker.BUDGET,
        "per_call_tokens": maker.PER_CALL_TOKENS,
        "sdk_version": maker.version("openai-codex"),
        "system": maker.SYSTEM,
        "output_schema": maker.OUTPUT_SCHEMA,
        "driver_sha256": {
            k: v for k, v in _settings()["driver_sha256"].items() if k != "revision"
        },
    }
    if any(parent.get(k) != v for k, v in expected.items()) or set(
        contract["parents"]
    ) != {"G0", "G1"}:
        raise ValueError("Original maker settings or sources changed")
    candidates = {}
    for branch in ("G0", "G1"):
        first = next(
            (
                e
                for e in events
                if e["kind"] == "offline"
                and e["purpose"] == "maker"
                and e["variant"] == branch
            ),
            None,
        )
        if first is None or first["id"] != contract["parents"][branch]:
            raise ValueError("Revision must inherit each branch's first candidate")
        candidates[branch] = verified_maker_result(pilot, events, first)
    exported = feedback(pilot, events, contract["feedback_windows"], candidates["G1"])
    if _read(contract["feedback"]) != exported:
        raise ValueError("Consumer feedback differs from its source dialogs")
    common, images, common_hash = maker.summarize_inputs(inputs, variant)
    prior_feedback = common.pop("user_feedback", [])
    if common_hash != parent["common_hash"]:
        raise ValueError("Original common sensor/action/image input changed")
    payload = {
        "common": common,
        "shared_observed_measurements": shared_measurements(exported),
        "previous_candidate": candidates[variant],
        "stage": "paired_refinement",
    }
    if variant == "G1":
        payload["user_feedback"] = {
            "original_development": prior_feedback,
            "offline_interactions": exported["windows"],
        }
    return payload, images


def validate_binding(
    pilot: Pilot, events: list[dict], variant: str, inputs: list, binding: dict
) -> tuple[dict, list[bytes]]:
    """Reconstruct the complete request before charging and again at freezing."""
    if set(binding) != {"contract", "request"}:
        raise ValueError("Revision needs immutable contract and request references")
    contract, request = _read(binding["contract"]), _read(binding["request"])
    payload, images = _materialize(pilot, events, contract, variant, inputs)
    expected = {
        "contract": binding["contract"],
        "variant": variant,
        "payload": payload,
        "input_hash": digest(payload),
        "prompt": maker.codex_sdk.request_prompt(SYSTEM, payload),
    }
    if request != expected:
        raise ValueError("Revision request does not match its frozen inputs")
    return payload, images


def prepare(pilot_root: str | Path, windows: list[dict]) -> dict:
    """Write one paired contract and both requests; never dispatch or reserve."""
    pilot = Pilot(pilot_root)
    windows = [
        {
            **window,
            **{key: str(Path(window[key]).resolve()) for key in ("first", "after")},
        }
        for window in windows
    ]

    def build(events):
        if any(e["kind"] == "frozen" for e in events):
            raise ValueError("Refinement is closed after freezing")
        parents = {}
        for variant in ("G0", "G1"):
            calls = [
                e
                for e in events
                if e["kind"] == "offline"
                and e["purpose"] == "maker"
                and e["variant"] == variant
            ]
            if len(calls) != 1:
                raise ValueError(
                    "Each branch must have exactly one prior maker request"
                )
            parents[variant] = calls[0]["id"]
        g1 = next(e for e in events if e.get("id") == parents["G1"])
        exported = feedback(
            pilot, events, windows, verified_maker_result(pilot, events, g1)
        )
        contract = {
            "schema_version": 2,
            "kind": "paired_refinement",
            "parent_contract": _file_refs({"parent": pilot.root / "maker-common.json"})[
                "parent"
            ],
            "settings": _settings(),
            "parents": parents,
            "feedback_windows": windows,
            "feedback": _save(pilot.root, "maker-feedback", exported),
        }
        contract_ref = _save(pilot.root, "maker-revision-contract", contract)
        attempts = [
            next(
                e["id"]
                for e in events
                if e["kind"] == "reserved" and e["cell"] == f"dev-{index:02d}"
            )
            for index in range(3, 7)
        ]
        bindings = {}
        for variant in ("G0", "G1"):
            inputs = pilot._maker_inputs(events, variant, attempts)
            payload, _ = _materialize(pilot, events, contract, variant, inputs)
            request = {
                "contract": contract_ref,
                "variant": variant,
                "payload": payload,
                "input_hash": digest(payload),
                "prompt": maker.codex_sdk.request_prompt(SYSTEM, payload),
            }
            bindings[variant] = {
                "contract": contract_ref,
                "request": _save(pilot.root, "maker-revision-request", request),
            }
        return bindings, None

    return pilot._transaction(build)


def run(pilot_root: str | Path, binding: dict) -> dict:
    """Use the remaining original maker call; no automatic retry or publication."""
    pilot = Pilot(pilot_root)
    request = _read(binding["request"])
    variant = request["variant"]
    attempts, refs, _, _, common_hash = maker.build_inputs(pilot, variant)
    payload, images = pilot._transaction(
        lambda events: (validate_binding(pilot, events, variant, refs, binding), None)
    )
    request_id = pilot.reserve_offline(
        "maker",
        variant,
        attempts,
        maker_budget=maker.BUDGET,
        max_tokens=maker.PER_CALL_TOKENS,
        revision=binding,
    )
    output = pilot.root / "maker" / request_id
    result = {
        "status": "failed",
        "budget_check": "not_passed",
        "token_limit_mode": "soft_limit_and_posthoc_check",
        "request_unit": "sdk_turn_provider_retries_unobservable",
        "request_id": request_id,
        "variant": variant,
        "common_hash": common_hash,
        "revision": binding,
        "artifact_dir": str(output.resolve()),
    }
    usage, started = {}, time.monotonic()
    try:
        output.mkdir(exist_ok=False)
        maker._write(output / "request.json", request)
        for index, image in enumerate(images):
            (output / f"image-{index:03d}.png").write_bytes(image)
        with (output / "events.jsonl").open("x") as journal:

            def record(event):
                nonlocal usage
                if event["method"] == "thread/tokenUsage/updated":
                    usage = event["payload"].get("tokenUsage", {})
                journal.write(
                    json.dumps(
                        clean({"elapsed_s": time.monotonic() - started, **event}),
                        allow_nan=False,
                    )
                    + "\n"
                )
                journal.flush()
                maker.os.fsync(journal.fileno())

            text, usage = maker.codex_sdk.complete_recorded(
                maker.MODEL,
                SYSTEM,
                payload,
                images,
                output_schema=maker.OUTPUT_SCHEMA,
                on_event=record,
                timeout_s=180,
            )
        (output / "response.txt").write_text(clean(text))
        tokens = maker._output_tokens(usage)
        if type(tokens) is not int or not 0 <= tokens <= maker.PER_CALL_TOKENS:
            raise ValueError(
                "Returned maker output usage missing or exceeds soft limit"
            )

        def previous(events):
            calls = [
                e
                for e in events
                if e["kind"] == "offline"
                and e["purpose"] == "maker"
                and e["variant"] == variant
                and e["id"] != request_id
            ]
            values = [
                maker._output_tokens(_result(events, e["id"]).get("usage", {}))
                for e in calls
            ]
            if any(type(value) is not int or value < 0 for value in values):
                raise ValueError("Prior maker output usage missing")
            return sum(values), None

        total = pilot._transaction(previous) + tokens
        if total > maker.BUDGET["max_tokens"]:
            raise ValueError("Maker branch output budget exceeded")
        wire = json.loads(text)
        Draft202012Validator(maker.OUTPUT_SCHEMA).validate(wire)
        candidate = {key: wire[key] for key in ("name", "description", "source")}
        candidate["parameters"] = json.loads(wire["parameters_json"])
        validate_tools([candidate])
        maker._write(output / "candidate.json", candidate)
        result.update(
            status="completed",
            budget_check="passed_posthoc",
            branch_output_tokens=total,
            candidate_sha256=digest(candidate),
            replay_status="not_run",
            publication_status="not_published",
        )
    except Exception as exc:
        result["error"] = clean(f"{type(exc).__name__}: {exc}")
    finally:
        result.update(usage=usage, elapsed_s=round(time.monotonic() - started, 3))
        try:
            if output.exists():
                maker._write(output / "result.json", result)
        finally:
            pilot.finish_offline(request_id, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-root", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare-windows", type=Path)
    action.add_argument("--run-binding", type=Path)
    args = parser.parse_args()
    result = (
        prepare(args.pilot_root, _json(args.prepare_windows))
        if args.prepare_windows
        else run(args.pilot_root, _json(args.run_binding))
    )
    print(json.dumps(result, ensure_ascii=False))
    if args.run_binding and result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
