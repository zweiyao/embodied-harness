# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Paired refinement uses recorded consumer dialogs, never simulator truth."""

import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from robots.univtac.pilot import digest, maker
from robots.univtac.pilot import maker_revision as module
from tests.unit_tests.robots.univtac.test_maker import answer
from tests.unit_tests.robots.univtac.test_maker import (
    pilot as stage_one_pilot,  # noqa: F401
)
from tests.unit_tests.robots.univtac.test_replay import sensors  # noqa: F401


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def read(path):
    return json.loads(Path(path).read_text())


def test_public_part_serialization_is_stable_across_python_processes():
    code = "from robots.univtac.pilot.maker_revision import _parts; import json; print(json.dumps(_parts([{'part_kind':'tool-call','tool_name':'observe','args':{},'tool_call_id':'one'}],None,{})))"
    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed}
        )
        for seed in ("1", "2")
    ]
    assert outputs[0] == outputs[1]


@pytest.fixture
def pair(stage_one_pilot, monkeypatch, tmp_path):  # noqa: F811
    pilot = stage_one_pilot
    monkeypatch.setattr(
        maker.codex_sdk,
        "complete_recorded",
        lambda *a, **k: (answer(), {"total": {"output_tokens": 20}}),
    )
    parents = {variant: maker.run(pilot.root, variant) for variant in ("G0", "G1")}
    assert all(row["status"] == "completed" for row in parents.values())
    candidate = read(Path(parents["G1"]["artifact_dir"]) / "candidate.json")
    declarations = [
        {
            "type": "function",
            "function": {
                key: candidate[key] for key in ("name", "description", "parameters")
            },
        }
    ]
    windows = []
    for row in pilot.summary()["rows"][2:4]:
        first_parts = [
            {
                "part_kind": "thinking",
                "content": "A service-returned thought, not ground truth.",
            },
            {"part_kind": "text", "content": "First inspect the image."},
            {
                "part_kind": "tool-call",
                "tool_name": "read_image",
                "args": {"view": "left"},
                "tool_call_id": "image-call",
            },
        ]
        window = {"attempt_id": row["attempt_id"]}
        for stage, purpose in (
            ("first", "tool_acceptance"),
            ("after", "after_native_observation"),
        ):
            directory = tmp_path / "dialogs" / row["id"] / stage
            directory.mkdir(parents=True)
            request = [
                {
                    "kind": "request",
                    "parts": [
                        {"part_kind": "user-prompt", "content": "Use available tools."}
                    ],
                }
            ]
            if stage == "after":
                image = b"recorded-test-image-pixels"
                name = f"inputs/{hashlib.sha256(image).hexdigest()}.bin"
                (directory / "inputs").mkdir()
                (directory / name).write_bytes(image)
                request += [
                    {"kind": "response", "parts": first_parts},
                    {
                        "kind": "request",
                        "parts": [
                            {
                                "part_kind": "tool-return",
                                "tool_name": "read_image",
                                "tool_call_id": "image-call",
                                "content": [
                                    json.dumps(
                                        {
                                            "step": 0,
                                            "image_metadata": {
                                                "group": "tactile",
                                                "sensor": "left",
                                                "image_size": [240, 320],
                                            },
                                        }
                                    ),
                                    {
                                        "kind": "binary",
                                        "identifier": "recorded-image",
                                        "data": {"artifact": name, "bytes": len(image)},
                                        "media_type": "image/png",
                                    },
                                ],
                            }
                        ],
                    },
                ]
            response = {
                "parts": first_parts
                if stage == "first"
                else [
                    {
                        "part_kind": "tool-call",
                        "tool_name": "move_eef",
                        "tool_call_id": "proposal",
                        "args": {"position": [0, 0, 0]},
                    }
                ],
                "finish_reason": "tool_call",
            }
            save(directory / "request.json", request)
            messages = []
            if stage == "after":
                content = request[-1]["parts"][0]["content"]
                messages = [
                    {
                        "role": "assistant",
                        "reasoning_content": first_parts[0]["content"],
                        "content": first_parts[1]["content"],
                        "tool_calls": [
                            {
                                "id": "image-call",
                                "type": "function",
                                "function": {
                                    "name": "read_image",
                                    "arguments": json.dumps(first_parts[2]["args"]),
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "image-call",
                        "content": json.dumps(
                            content[:-1] + ["See file recorded-image."]
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": '<tool_result tool_name="read_image" tool_call_id="image-call" file_id="recorded-image">',
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,"
                                    + base64.b64encode(image).decode()
                                },
                            },
                        ],
                    },
                ]
            save(
                directory / "request-wire.json",
                {"model": "qwen3.8-max", "tools": declarations, "messages": messages},
            )
            save(directory / "response.json", response)
            # Forbidden files exist deliberately; the exporter must not open them.
            save(directory / "review.json", {"hidden_target": "DO_NOT_FORWARD"})
            save(directory / "evaluator.json", {"native_success": "DO_NOT_FORWARD"})
            request_id = pilot.reserve_offline(purpose, "G1", [row["attempt_id"]])
            result = {
                "request_id": request_id,
                "status": "completed",
                "actions_executed": 0,
                "wire_sha256": hashlib.sha256(
                    (directory / "request-wire.json").read_bytes()
                ).hexdigest(),
                "usage": {"output_tokens": 20},
                "total_s": 1,
            }
            save(directory / "result.json", result)
            pilot.finish_offline(request_id, result)
            window[stage] = str(directory)
        windows.append(window)
    return pilot, windows, parents


def frozen_bundle(pilot, results):
    native = {
        "name": "observe",
        "description": "Observe",
        "parameters": {},
        "source": "native",
    }
    candidates = {
        variant: read(Path(result["artifact_dir"]) / "candidate.json")
        for variant, result in results.items()
    }
    attempts = maker.build_inputs(pilot, "G0")[0]
    return {
        "conditions": {
            name: {
                "tools": [native]
                + ([candidates["G0" if name == "D" else "G1"]] if name in "DE" else []),
                "guidance": "fixed",
                "parameters": {},
            }
            for name in "CDEF"
        },
        "controller": {"fixed": True},
        "models": {"fixed": True},
        "memory": {},
        "code_revision": "test",
        "base_tool": candidates["G0"],
        "maker_budget": maker.BUDGET,
        "maker_input_attempts": attempts,
        "validation_evidence": {"replay": "fixture"},
    }


def test_prepare_preserves_original_common_and_only_g1_gets_actual_dialogs(pair):
    pilot, windows, _ = pair
    common_before = (pilot.root / "maker-common.json").read_bytes()
    bindings = module.prepare(pilot.root, windows)
    assert module.prepare(pilot.root, windows) == bindings
    assert pilot.summary()["offline_requests"] == 6
    requests = {v: read(b["request"]["path"]) for v, b in bindings.items()}
    payload0, payload1 = (requests[v]["payload"] for v in ("G0", "G1"))
    assert payload0["common"] == payload1["common"]
    assert (
        payload0["shared_observed_measurements"]
        == payload1["shared_observed_measurements"]
    )
    assert len(payload0["shared_observed_measurements"]["measurements"]) == 2
    assert "image-call" not in json.dumps(payload0["shared_observed_measurements"])
    assert "user_feedback" not in payload0 and "user_feedback" not in payload0["common"]
    assert (
        digest(payload0["common"])
        == read(pilot.root / "maker-common.json")["common_hash"]
    )
    assert (pilot.root / "maker-common.json").read_bytes() == common_before
    feedback = payload1["user_feedback"]["offline_interactions"]
    assert len(feedback) == 2
    assert [r["tool_results_seen_by_model"] for r in feedback[0]["responses"]] == [
        False,
        True,
    ]
    assert feedback[0]["responses"][1]["returned_parts"][0]["tool_name"] == "move_eef"
    assert all(r["actions_executed"] == 0 for r in feedback[0]["responses"])
    assert "image_sha256" in json.dumps(feedback)
    assert "DO_NOT_FORWARD" not in json.dumps(payload1)
    assert "data:image/" not in json.dumps(payload1)
    assert "service-returned thought" in json.dumps(payload1)
    contract = read(bindings["G0"]["contract"]["path"])
    assert contract["schema_version"] == 2
    assert contract["settings"]["timeout_s"] == 180
    assert bindings["G0"]["contract"] == bindings["G1"]["contract"]
    assert "paired refinement" in requests["G0"]["prompt"]


def test_two_remaining_calls_are_charged_recorded_and_freeze_the_actual_source(
    pair, monkeypatch
):
    pilot, windows, _ = pair
    bindings = module.prepare(pilot.root, windows)
    calls = []

    def complete(model, system, payload, images, **options):
        assert model == maker.MODEL and system == module.SYSTEM
        assert (
            options["timeout_s"] == 180
            and options["output_schema"] == maker.OUTPUT_SCHEMA
        )
        calls.append((payload, images))
        options["on_event"](
            {"method": "returned", "payload": {"access_token": "do-not-record"}}
        )
        output = json.loads(answer())
        output["description"] += " refined " + str(len(calls))
        return json.dumps(output), {"total": {"output_tokens": 30}}

    monkeypatch.setattr(maker.codex_sdk, "complete_recorded", complete)
    results = {v: module.run(pilot.root, bindings[v]) for v in ("G0", "G1")}
    assert all(
        r["status"] == "completed" and r["branch_output_tokens"] == 50
        for r in results.values()
    )
    assert calls[0][1] == calls[1][1]
    assert calls[0][0]["common"] == calls[1][0]["common"]
    assert (
        calls[0][0]["shared_observed_measurements"]
        == calls[1][0]["shared_observed_measurements"]
    )
    assert pilot.summary()["offline_requests"] == 8
    for v, result in results.items():
        root = Path(result["artifact_dir"])
        assert read(root / "request.json") == read(bindings[v]["request"]["path"])
        assert "do-not-record" not in (root / "events.jsonl").read_text()
        assert result["publication_status"] == "not_published"
    bundle = frozen_bundle(pilot, results)
    pilot.freeze(bundle)
    assert pilot.load_freeze(digest(bundle)) == bundle
    with pytest.raises(ValueError, match="closed after freezing"):
        module.run(pilot.root, bindings["G0"])


@pytest.mark.parametrize("usage", [{}, {"total": {"output_tokens": 8193}}])
def test_failed_usage_retains_charge_and_cannot_freeze(pair, monkeypatch, usage):
    pilot, windows, parents = pair
    bindings = module.prepare(pilot.root, windows)
    monkeypatch.setattr(
        maker.codex_sdk, "complete_recorded", lambda *a, **k: (answer(), usage)
    )
    result = module.run(pilot.root, bindings["G0"])
    assert result["status"] == "failed" and pilot.summary()["offline_requests"] == 7
    with pytest.raises(ValueError, match="must complete"):
        pilot.freeze(frozen_bundle(pilot, parents))
    with pytest.raises(ValueError):
        module.run(pilot.root, bindings["G0"])
    assert pilot.summary()["offline_requests"] == 7
    # The other pre-specified branch still runs with its original frozen input,
    # even when G0's second request has no usable output/usage.
    monkeypatch.setattr(
        maker.codex_sdk,
        "complete_recorded",
        lambda *a, **k: (answer(), {"total": {"output_tokens": 30}}),
    )
    other = module.run(pilot.root, bindings["G1"])
    assert other["status"] == "completed" and pilot.summary()["offline_requests"] == 8
    assert read(Path(other["artifact_dir"]) / "request.json") == read(
        bindings["G1"]["request"]["path"]
    )
    with pytest.raises(ValueError, match="must complete"):
        pilot.freeze(frozen_bundle(pilot, {**parents, "G1": other}))


@pytest.mark.parametrize(
    "change", ["source_dialog", "image", "request_binding", "wrong_source"]
)
def test_changed_bound_evidence_or_non_development_source_never_dispatches(
    pair, monkeypatch, change
):
    pilot, windows, _ = pair
    bindings = module.prepare(pilot.root, windows)
    if change == "source_dialog":
        path = Path(windows[0]["after"]) / "response.json"
        save(path, {"parts": [{"part_kind": "text", "content": "changed"}]})
    elif change == "image":
        next((Path(windows[0]["after"]) / "inputs").iterdir()).write_bytes(b"changed")
    elif change == "request_binding":
        path = Path(bindings["G0"]["request"]["path"])
        data = read(path)
        data["payload"]["previous_candidate"]["source"] += "\n# changed"
        save(path, data)
    else:
        windows[0]["attempt_id"] = pilot.summary()["rows"][0]["attempt_id"]
        with pytest.raises(ValueError, match="maker inputs"):
            module.prepare(pilot.root, windows)
        return
    monkeypatch.setattr(
        maker.codex_sdk,
        "complete_recorded",
        lambda *a, **k: pytest.fail("must not dispatch"),
    )
    with pytest.raises(ValueError):
        module.run(pilot.root, bindings["G0"])
    assert pilot.summary()["offline_requests"] == 6


@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_duplicate_tool_returns_are_not_complete_interaction(
    pair, duplicate
):
    pilot, windows, _ = pair
    path = Path(windows[0]["after"]) / "request.json"
    data = read(path)
    data[-1]["parts"] = data[-1]["parts"] * 2 if duplicate else []
    save(path, data)
    with pytest.raises(ValueError, match="tool returns differ"):
        module.prepare(pilot.root, windows)
    assert pilot.summary()["offline_requests"] == 6


@pytest.mark.parametrize("field", ["measurement", "first_arguments", "image_reference"])
def test_initial_binding_checks_recorded_dialog_against_ledger_wire(pair, field):
    pilot, windows, _ = pair
    path = Path(windows[0]["after"]) / "request.json"
    data = read(path)
    if field == "measurement":
        data[-1]["parts"][0]["content"][0] = json.dumps({"step": 0, "depth_m": [999]})
    elif field == "first_arguments":
        data[1]["parts"][-1]["args"]["view"] = "changed"
    else:
        data[-1]["parts"][0]["content"][-1]["data"]["artifact"] = (
            "inputs/" + "a" * 64 + ".bin"
        )
    save(path, data)
    with pytest.raises(ValueError, match="from the bound wire"):
        module.prepare(pilot.root, windows)
    assert pilot.summary()["offline_requests"] == 6


def test_only_one_refined_branch_and_changed_candidate_cannot_freeze(pair):
    pilot, windows, parents = pair
    bindings = module.prepare(pilot.root, windows)
    result = module.run(pilot.root, bindings["G0"])
    current = {**parents, "G0": result}
    with pytest.raises(ValueError, match="same paired refinement"):
        pilot.freeze(frozen_bundle(pilot, current))
    final = module.run(pilot.root, bindings["G1"])
    bundle = frozen_bundle(pilot, {**current, "G1": final})
    bad = copy.deepcopy(bundle)
    bad["conditions"]["E"]["tools"][-1]["source"] += "\n# not the maker's output"
    with pytest.raises(ValueError, match="differs from its maker candidate"):
        pilot.freeze(bad)
    save(
        Path(final["artifact_dir"]) / "candidate.json",
        bad["conditions"]["E"]["tools"][-1],
    )
    with pytest.raises(ValueError, match="source hash mismatch"):
        pilot.freeze(bundle)


def test_revision_is_not_a_way_to_add_unbudgeted_diagnostic_calls(pair):
    pilot, windows, _ = pair
    bindings = module.prepare(pilot.root, windows)
    attempts = maker.build_inputs(pilot, "G0")[0]
    with pytest.raises(ValueError, match="only valid for maker"):
        pilot.reserve_offline("diagnostic", "G0", attempts, revision=bindings["G0"])
    module.run(pilot.root, bindings["G0"])
    with pytest.raises(ValueError, match="must use paired refinement"):
        pilot.reserve_offline(
            "maker", "G1", attempts, maker_budget=maker.BUDGET, max_tokens=8192
        )


def test_shared_measurements_retain_recorded_coordinates_but_no_errors_or_query_order(
    pair,
):
    pilot, windows, _ = pair
    binding = module.prepare(pilot.root, windows)["G0"]
    exported = read(read(binding["contract"]["path"])["feedback"]["path"])
    first, after = exported["windows"][0]["responses"]
    for suffix, result in (
        (
            "ok",
            {
                "step": 7,
                "camera": "head",
                "pixels_rc": [[13, 29]],
                "depth_m": [0.987654],
                "calibration": {"camera_convention": "ros_optical", "depth_units": "m"},
            },
        ),
        ("bad", {"step": 7, "error": "Unusable query"}),
        ("missing_frame", {"camera": "head", "depth_m": [0.123]}),
    ):
        first["returned_parts"].append(
            {
                "part_kind": "tool-call",
                "tool_name": "depth_points",
                "tool_call_id": suffix,
                "args": {"camera": "head", "pixels_rc": [[13, 29]]},
            }
        )
        after["preceding_tool_returns"].append(
            {
                "part_kind": "tool-return",
                "tool_name": "depth_points",
                "tool_call_id": suffix,
                "content": [json.dumps(result)],
            }
        )
    shared = module.shared_measurements(exported)
    measured = next(
        row for row in shared["measurements"] if row["tool_name"] == "depth_points"
    )
    assert measured["result"]["depth_m"] == [0.987654]
    assert measured["result"]["step"] == 7
    assert measured["result"]["calibration"]["camera_convention"] == "ros_optical"
    assert measured["arguments"]["pixels_rc"] == [[13, 29]]
    assert "Unusable query" not in json.dumps(shared)
    assert "0.123" not in json.dumps(shared)
    assert "tool_call_id" not in json.dumps(shared)
    first["returned_parts"].reverse()
    after["preceding_tool_returns"].reverse()
    after["preceding_tool_returns"] += after["preceding_tool_returns"]
    assert module.shared_measurements(exported) == shared
