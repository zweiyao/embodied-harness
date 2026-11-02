# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""One recorded G0/G1 maker request from the four allowed development runs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import time
from importlib.metadata import version
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from jsonschema import Draft202012Validator
from PIL import Image

from robots.libero.research import codex_sdk
from robots.libero.research.library import validate_tools
from robots.univtac.pilot import Pilot, digest
from robots.univtac.pilot.evidence import _scrub
from robots.univtac.pilot.replay import load_frames
from rpent.dashboard.workbench import clean

BUDGET = {"max_calls": 2, "max_tokens": 16384}
PER_CALL_TOKENS = 8192
MODEL = "gpt-6-astra"
BASE_SOURCE = "def run(frames, params):\n    return {}\n"
SYSTEM = """Develop one reusable perception tool from supplied robot observations and actions.
Return JSON with name, description, parameters_json (a JSON object schema encoded as a string),
and source defining run(frames, params) -> concise finite JSON dict. Name must start sensor_.
Use NumPy and Python standard library only. No files, network, GPU, model calls or motion control.
Compute observable measurements and uncertainty; never encode task IDs, coordinates, recipes,
hidden geometry or success labels. You may retain an empty measurement if evidence is insufficient.
The initial code is an empty run skeleton, not a prior candidate. No evaluation outcome is supplied.
Keep the response within 8192 output tokens. This is a soft instruction, checked against returned usage.
Input contract: frames oldest to newest, 1..4 complete recorded frames; step, cameras.head/wrist
with RGB and depth arrays plus calibration; state.eef_pose_wxyz [x,y,z,qw,qx,qy,qz] in world metres;
tactile.left/right with native RGB, depth, reference_rgb/reference_kind and marker_reference,
marker_current, marker_displacement arrays. Read supplied metadata for dimensions, units and axes.
Marker rows may be independently resampled/shuffled; row identity across frames is not guaranteed.
Episode-initial tactile reference may already be loaded. Native tactile depth is sensor-camera depth,
not indentation. Image/marker differences are not calibrated force. Missing data is not zero.
The maker receives deterministic sampled summaries and original RGB pixels; generated tools receive
the full arrays. Do not infer object progress or task success solely from hand travel or deformation.
"""
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", "parameters_json", "source"],
    "properties": {
        key: {"type": "string"}
        for key in ("name", "description", "parameters_json", "source")
    },
}


def _array(value):
    """Serialize a bounded numeric array; nonfinite samples are missing."""
    array = np.asarray(value)
    return np.where(np.isfinite(array), array, None).tolist()


def _numeric(value):
    if isinstance(value, np.ndarray):
        return _array(value)
    if isinstance(value, dict):
        return {key: _numeric(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_numeric(item) for item in value]
    return value


def _depth(value):
    array = np.asarray(value)
    finite = array[np.isfinite(array)]
    rows = np.linspace(0, array.shape[0] - 1, min(8, array.shape[0]), dtype=int)
    cols = np.linspace(0, array.shape[1] - 1, min(8, array.shape[1]), dtype=int)
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "finite_fraction": float(finite.size / array.size),
        "quantiles_0_25_50_75_100": np.percentile(finite, [0, 25, 50, 75, 100]).tolist()
        if finite.size
        else None,
        "sample_rows": rows.tolist(),
        "sample_columns": cols.tolist(),
        "sample_values": _array(array[np.ix_(rows, cols)]),
    }


def summarize_inputs(refs, variant, *, frames_per_run=4):
    """Select up to four evenly spaced frames/run without inspecting outcomes."""
    if not 1 <= frames_per_run <= 4:
        raise ValueError("Select one to four maker frames per run")
    common, feedback, images, identities = [], [], [], []
    for entry in refs:
        files, attempt = entry["files"], entry["attempt_id"]
        archive_path = Path(files["sensors"]["path"])
        with ZipFile(archive_path) as archive:
            steps = json.loads(archive.read("manifest.json"))["steps"]
        selected = sorted(
            set(
                np.linspace(
                    0, len(steps) - 1, min(frames_per_run, len(steps)), dtype=int
                )
            )
        )
        frames = []
        for index in selected:
            frame = load_frames(archive_path, step=int(index))[-1]
            summary = {
                key: value
                for key, value in frame.items()
                if key not in {"cameras", "tactile"}
            }
            for group in ("cameras", "tactile"):
                summary[group] = {}
                for name, sensor in frame.get(group, {}).items():
                    compact = {}
                    for key, value in sensor.items():
                        if isinstance(value, np.ndarray):
                            if key in {"rgb", "reference_rgb"}:
                                compact[key] = {
                                    "shape": list(value.shape),
                                    "dtype": str(value.dtype),
                                }
                                if key == "rgb":
                                    buffer = io.BytesIO()
                                    Image.fromarray(
                                        np.clip(np.rint(value), 0, 255).astype(np.uint8)
                                    ).save(buffer, format="PNG")
                                    image = buffer.getvalue()
                                    identity = {
                                        "index": len(images),
                                        "attempt_id": attempt,
                                        "step": frame["step"],
                                        "sensor": f"{group}.{name}",
                                        "sha256": hashlib.sha256(image).hexdigest(),
                                    }
                                    compact[key]["image_index"] = len(images)
                                    identities.append(identity)
                                    images.append(image)
                            elif key == "depth":
                                compact[key] = _depth(value)
                            else:
                                compact[key] = {
                                    "shape": list(value.shape),
                                    "dtype": str(value.dtype),
                                    "values": _array(value),
                                }
                        else:
                            compact[key] = value
                    summary[group][name] = compact
            frames.append(_numeric(summary))
        common.append(
            {
                "attempt_id": attempt,
                "frames": frames,
                "actions": _scrub(
                    json.loads(Path(files["actions"]["path"]).read_text())
                ),
                "input_hashes": {
                    key: files[key]["sha256"] for key in ("sensors", "actions")
                },
            }
        )
        if "feedback" in files:
            feedback.append(
                {
                    "attempt_id": attempt,
                    "sha256": files["feedback"]["sha256"],
                    "feedback": _scrub(
                        json.loads(Path(files["feedback"]["path"]).read_text())
                    ),
                }
            )
    payload = {
        "serializer": "univtac-maker-v1",
        "base_source": BASE_SOURCE,
        "development": common,
        "images": identities,
    }
    common_hash = digest(payload)
    if variant == "G1":
        payload["user_feedback"] = feedback
    return payload, images, common_hash


def build_inputs(pilot: Pilot, variant: str):
    """Gate the real maker on all four finished development inputs."""
    rows = {row["id"]: row for row in pilot.summary()["rows"]}
    attempts = [rows[f"dev-{index:02d}"]["attempt_id"] for index in range(3, 7)]
    refs = pilot.maker_inputs(variant, attempts)
    payload, images, common_hash = summarize_inputs(refs, variant)
    # Verify references again after decoding, before reserving or dispatching.
    if pilot.maker_inputs(variant, attempts) != refs:
        raise ValueError("Development inputs changed while decoding")
    return attempts, refs, payload, images, common_hash


def _write(path, value):
    with Path(path).open("x") as stream:
        json.dump(clean(value), stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def _output_tokens(usage):
    total = usage.get("total", {})
    return total.get("output_tokens", total.get("outputTokens"))


def run(pilot_root, variant):
    """Reserve once, generate once, then reject missing/excess returned usage."""
    pilot = Pilot(pilot_root)
    attempts, refs, payload, images, common_hash = build_inputs(pilot, variant)
    contract = {
        "common_hash": common_hash,
        "system": SYSTEM,
        "output_schema": OUTPUT_SCHEMA,
        "model": MODEL,
        "reasoning_effort": "low",
        "timeout_s": 180,
        "maker_budget": BUDGET,
        "per_call_tokens": PER_CALL_TOKENS,
        "sdk_version": version("openai-codex"),
        "driver_sha256": {
            name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for name, path in (("maker", __file__), ("codex_sdk", codex_sdk.__file__))
        },
    }
    pairing = pilot.root / "maker-common.json"
    if pairing.exists():
        if json.loads(pairing.read_text()) != contract:
            raise ValueError("G0/G1 common inputs or generation settings differ")
    else:
        _write(pairing, contract)
    request = pilot.reserve_offline(
        "maker", variant, attempts, maker_budget=BUDGET, max_tokens=PER_CALL_TOKENS
    )
    output = pilot.root / "maker" / request
    started = time.monotonic()
    result = {
        "status": "failed",
        "budget_check": "not_passed",
        "token_limit_mode": "soft_limit_and_posthoc_check",
        "request_unit": "sdk_turn_provider_retries_unobservable",
        "request_id": request,
        "variant": variant,
        "common_hash": common_hash,
        "artifact_dir": str(output.resolve()),
    }
    latest_usage = {}
    try:
        output.mkdir(parents=True, exist_ok=False)
        _write(
            output / "request.json",
            {
                **contract,
                "variant": variant,
                "input_refs": refs,
                "payload": payload,
                "prompt": codex_sdk.request_prompt(SYSTEM, payload),
                "input_hash": digest(payload),
            },
        )
        for index, image in enumerate(images):
            (output / f"image-{index:03d}.png").write_bytes(image)
        with (output / "events.jsonl").open("x") as journal:

            def record(event):
                nonlocal latest_usage
                if event["method"] == "thread/tokenUsage/updated":
                    latest_usage = event["payload"].get("tokenUsage", {})
                journal.write(
                    json.dumps(
                        clean({"elapsed_s": time.monotonic() - started, **event}),
                        allow_nan=False,
                    )
                    + "\n"
                )
                journal.flush()
                os.fsync(journal.fileno())

            text, usage = codex_sdk.complete_recorded(
                MODEL,
                SYSTEM,
                payload,
                images,
                output_schema=OUTPUT_SCHEMA,
                on_event=record,
                timeout_s=180,
            )
        (output / "response.txt").write_text(clean(text))
        latest_usage = usage
        tokens = _output_tokens(usage)
        if type(tokens) is not int or tokens < 0:
            raise ValueError("Returned total output token usage is missing")
        if tokens > PER_CALL_TOKENS:
            raise ValueError("Returned output tokens exceed the soft limit")

        def previous_usage(events):
            ids = {
                event["id"]
                for event in events
                if event["kind"] == "offline"
                and event["purpose"] == "maker"
                and event["variant"] == variant
                and event["id"] != request
            }
            totals = {
                event["id"]: _output_tokens(event["result"].get("usage", {}))
                for event in events
                if event["kind"] == "offline_result" and event["id"] in ids
            }
            if set(totals) != ids or any(
                type(value) is not int for value in totals.values()
            ):
                raise ValueError(
                    "Prior maker output usage is unavailable; branch budget cannot be verified"
                )
            return sum(totals.values()), None

        branch_tokens = pilot._transaction(previous_usage) + tokens
        result["branch_output_tokens"] = branch_tokens
        if branch_tokens > BUDGET["max_tokens"]:
            raise ValueError("Returned branch output tokens exceed the shared budget")
        result["budget_check"] = "passed_posthoc"
        wire = json.loads(text)
        Draft202012Validator(OUTPUT_SCHEMA).validate(wire)
        tool = {key: wire[key] for key in ("name", "description", "source")}
        tool["parameters"] = json.loads(wire["parameters_json"])
        validate_tools([tool])
        _write(output / "candidate.json", tool)
        result.update(
            status="completed",
            candidate_sha256=digest(tool),
            replay_status="not_run",
            publication_status="not_published",
        )
    except Exception as exc:
        result["error"] = clean(f"{type(exc).__name__}: {exc}")
    finally:
        result.update(
            usage=latest_usage, elapsed_s=round(time.monotonic() - started, 3)
        )
        try:
            if output.exists():
                _write(output / "result.json", result)
        finally:
            pilot.finish_offline(request, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-root", required=True, type=Path)
    parser.add_argument("--variant", choices=("G0", "G1"), required=True)
    args = parser.parse_args()
    result = run(args.pilot_root, args.variant)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
