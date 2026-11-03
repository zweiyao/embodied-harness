# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Development isolation, measured stopping and bounded optimization contracts."""

import json

import pytest

from examples.univtac import develop_tools as module


def row(success=True, tokens=100):
    return {
        "official_success": success,
        "input_tokens": tokens,
        "output_tokens": 10,
        "elapsed_s": 1,
    }


def test_success_ranks_before_tokens_and_missing_usage_cannot_win():
    base = module.score([row(), row(), row(False)])
    assert module.better(module.score([row(tokens=1000)] * 3), base)
    assert not module.better(module.score([row(False, 1)] * 3), base)
    unknown = module.score([row(tokens=None)] * 3)
    assert unknown["mean_total_tokens"] is None
    assert module.better(unknown, base)  # Success improves even when cost is unknown.
    assert not module.better(unknown, module.score([row()] * 3))


def test_early_stop_requires_measurement_and_astra_assessment():
    base = module.score([row()] * 3)
    candidate = module.score([row(tokens=70)] * 3)
    judge = dict.fromkeys(
        ("token_benefit", "success_benefit", "stop_recommended"), True
    )
    assert module.early_stop(candidate, base, judge)
    assert module.early_stop(candidate, base, {**judge, "success_benefit": False})
    assert not module.early_stop(candidate, base, {**judge, "token_benefit": False})
    assert not module.early_stop(module.score([row(tokens=95)] * 3), base, judge)
    assert not module.early_stop(
        module.score([row(tokens=10), row(tokens=10), row(False, 10)]), base, judge
    )


def test_held_out_task_is_rejected_before_reading_observations(tmp_path):
    with pytest.raises(ValueError, match="all be task 0"):
        module.development_inputs([{"task": 1, "path": "not-read"}])
    (tmp_path / "dashboard_config.json").write_text(
        json.dumps({"robot": "univtac", "task": {"task": 2}})
    )
    with pytest.raises(ValueError, match="Actual archived task"):
        module.development_inputs([{"task": 0, "path": str(tmp_path)}])


def test_failed_tool_calls_are_not_counted_as_adoption(tmp_path):
    events = [
        {"kind": "tool_response", "payload": {"name": module.NAME, "result": result}}
        for result in (
            {"value": 1},
            {"error": "invalid parameters"},
            {"errors": ["missing frame"]},
        )
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    assert module.valid_tool_calls([{"path": str(tmp_path)}]) == {
        "valid_calls": 1,
        "error_calls": 2,
    }


def test_maker_keeps_the_queried_geometry_frame_and_final_temporal_pair():
    def query(step, region):
        return {
            "kind": "tool_response",
            "payload": {
                "name": "read_depth",
                "result": {"step": step, "region_rc": region},
            },
        }

    events = [query(4, [1, 2, 3, 4]), query(7, None), query(99, [1, 2, 3, 4])]
    assert module.maker_frame_steps(events, 10) == [4, 9, 10]
    assert module.maker_frame_steps([], 10) == [0, 9, 10]
    assert module.maker_frame_steps([], 0) == [0]


@pytest.mark.parametrize(
    "scenario,optimizations",
    [
        ("improve", 5),
        ("no_gain", 5),
        ("input_error", 5),
        ("improve", 3),
        ("recorded", 2),
        ("wrong_library", 1),
        ("timeout", 3),
    ],
)
def test_five_optimizations_then_frozen_test_without_test_feedback(
    tmp_path, monkeypatch, scenario, optimizations
):
    calls = []

    class FakeExperiment:
        def __init__(self, url, root):
            self.hashes, self.base_config = {}, {}
            self.server_id = "test"

        def api(self, path, payload=None):
            if scenario == "wrong_library" and path.endswith("tools"):
                return {"tools": [{"id": "generated:missing", "selectable": True}]}
            return (
                {"session_state": "ready", "server_id": self.server_id}
                if path.endswith("state")
                else {"tools": []}
                if path.endswith("tools")
                else {}
            )

        def status(self, **kwargs):
            pass

        def group(self, label, trials, tools):
            calls.append((label, trials, tools))
            return [
                {
                    "task": task,
                    "seed": seed,
                    "run_id": str(seed),
                    "tool_calls": {module.NAME: 1},
                    **row(
                        tokens=90
                        if scenario in ("improve", "recorded")
                        and label != "development-baseline"
                        else 100
                    ),
                }
                for task, seed in trials
            ]

    class FakeSandbox:
        image = "immutable-image"

        def __init__(self, image):
            pass

        def run(self, *args):
            return {"evidence": "test"}

    makers = []

    def complete(output, system, payload, images, schema):
        if scenario == "timeout":
            raise TimeoutError()
        if scenario == "input_error":
            raise module.MakerInputBudgetError("input exceeds budget")
        if schema == module.JUDGE_SCHEMA:
            return {
                "token_benefit": True,
                "success_benefit": False,
                "stop_recommended": False,
                "reason": "not enough evidence",
            }
        assert scenario != "recorded", (
            "Recorded candidates must not issue maker requests"
        )
        assert all(row["task"] == 0 for row in makers[-1])
        return {
            "name": module.NAME,
            "description": "test",
            "source": "def run(frames, params):\n    return {}\n",
            "parameters_json": '{"type":"object"}',
            "replay_params_json": "{}",
            "reason": "test",
        }

    def inputs(rows):
        makers.append(rows)
        return (
            {},
            [],
            [{"attempt_id": "dev", "files": {"sensors": {"path": "development-only"}}}],
        )

    monkeypatch.chdir(tmp_path)
    (tmp_path / "research.md").write_text("development only")
    source = tmp_path / "robots/univtac/pilot"
    source.mkdir(parents=True)
    for name in ("maker.py", "evidence.py"):
        (source / name).write_text("# provenance fixture\n")
    monkeypatch.setattr(module, "Experiment", FakeExperiment)
    monkeypatch.setattr(module, "Sandbox", FakeSandbox)
    monkeypatch.setattr(module, "development_inputs", inputs)
    monkeypatch.setattr(module, "completion", complete)
    monkeypatch.setattr(module, "publish", lambda *a, **k: "v1")
    monkeypatch.setattr(module, "load_frames", lambda *a, **k: [{"step": 0}])
    monkeypatch.setattr(module, "log_iteration", lambda *a: None)
    monkeypatch.setattr(
        module, "valid_tool_calls", lambda rows: {"valid_calls": 3, "error_calls": 0}
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "develop_tools",
            "--output",
            str(tmp_path / "experiment"),
            "--library",
            str(tmp_path / "library"),
            "--max-optimizations",
            str(optimizations),
        ],
    )
    if scenario == "recorded":
        import sys

        origins = []
        for index in range(optimizations):
            origin = tmp_path / f"recorded-{index}"
            (origin / "maker").mkdir(parents=True)
            tool = {
                "name": module.NAME,
                "description": "test",
                "source": "def run(frames, params):\n    return {}\n",
                "parameters": {"type": "object"},
            }
            wire = {k: v for k, v in tool.items() if k != "parameters"}
            wire.update(
                parameters_json=json.dumps(tool["parameters"]),
                replay_params_json="{}",
                reason="test",
            )
            (origin / "candidate.json").write_text(json.dumps(tool))
            (origin / "maker/response.json").write_text(
                json.dumps({"text": json.dumps(wire)})
            )
            origins.append(str(origin))
        sys.argv.extend(["--candidates-from", *origins])
    if scenario == "wrong_library":
        with pytest.raises(ValueError, match="dashboard's active generated tools"):
            module.main()
        assert not calls and not makers
        return
    if scenario in ("input_error", "timeout"):
        with pytest.raises(
            module.MakerInputBudgetError if scenario == "input_error" else TimeoutError
        ):
            module.main()
        assert len(makers) == 1
        assert len(calls) == 1
        assert not (tmp_path / "experiment/freeze.json").exists()
        return
    module.main()
    if scenario == "recorded":
        for index in range(1, optimizations + 1):
            reused = json.loads(
                (
                    tmp_path / f"experiment/iteration-{index}/maker-reused.json"
                ).read_text()
            )
            assert reused["new_maker_requests"] == 0
            assert not (tmp_path / f"experiment/iteration-{index}/maker").exists()
    assert len(makers) == optimizations
    if scenario == "no_gain":
        assert len(calls) == optimizations + 1
        assert (
            json.loads((tmp_path / "experiment/final.json").read_text())["test"] == []
        )
        return
    assert len(calls) == optimizations + 2  # baseline, revisions, frozen evaluation
    assert all(task == 0 for _, trials, _ in calls[:-1] for task, _ in trials)
    assert calls[-1][1] == [(task, seed) for task in (1, 2) for seed in range(5)]
    assert len([name for name in calls[-1][2] if name.startswith("generated:")]) == 1
    assert (tmp_path / "experiment/freeze.json").exists()


def test_compact_input_keeps_paired_markers_call_order_errors_and_source_once():
    markers = [[float(i), float(i + 1)] for i in range(1500)]
    sensor = {
        name: {"shape": [1500, 2], "values": markers}
        for name in ("marker_reference", "marker_current", "marker_displacement")
    }
    calls = [
        {
            "name": module.NAME,
            "arguments": {},
            "result": {"step": i, "text": "x" * 6000},
        }
        for i in range(80)
    ]
    calls[17]["result"] = {"step": 17, "error": "invalid region"}
    payload = {
        "base_source": "UNIQUE_SOURCE",
        "previous_candidate": {"source": "UNIQUE_SOURCE"},
        "development": [{"frames": [{"step": 8, "tactile": {"left": sensor}}]}],
        "user_feedback": [{"feedback": {"calls": calls}}],
    }
    original = json.dumps(payload)
    compact = module.compact_maker_input(payload)
    assert json.dumps(payload) == original
    assert (
        len(module.codex_sdk.request_prompt(module.MAKER, compact))
        < module.MAKER_INPUT_CHARS
    )
    assert json.dumps(compact).count("UNIQUE_SOURCE") == 1
    sampled = compact["development"][0]["frames"][0]["tactile"]["left"]
    assert (
        sampled["marker_reference"]["sample_indices"]
        == sampled["marker_current"]["sample_indices"]
    )
    assert len(sampled["marker_current"]["values"]) == 32
    assert sampled["marker_current"]["original_shape"] == [1500, 2]
    feedback = compact["user_feedback"][0]["feedback"]
    assert len(feedback["call_sequence"]) == 80
    assert {17, 79}.issubset(feedback["selected_call_indices"])
    assert feedback["omitted_call_details"] > 0


def test_exact_sdk_text_budget_checked_before_any_model_request(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Oversized input must not reach the SDK")

    monkeypatch.setattr(module.codex_sdk, "complete", forbidden)
    # JSON ASCII escaping means Python string length alone is insufficient.
    payload = {"text": "深" * (module.MAKER_INPUT_CHARS // 5)}
    with pytest.raises(module.MakerInputBudgetError):
        module.completion(tmp_path / "maker", "test", payload, [], module.MAKER_SCHEMA)
    audit = json.loads((tmp_path / "maker/input-budget.json").read_text())
    assert audit["characters"] > audit["limit"]
    assert module.input_budget_failure(
        RuntimeError("Input exceeds the maximum length of 1048576 characters.")
    )
    assert not module.input_budget_failure(ValueError("invalid tool JSON"))


def test_group_stops_after_first_connection_error(tmp_path, monkeypatch):
    experiment = module.Experiment.__new__(module.Experiment)
    experiment.root = tmp_path
    experiment.server_id = "server"
    experiment.hashes = {}
    config = dict.fromkeys(
        ("model", "reasoning_effort", "max_turns", "max_tokens", "planner_timeout_s"), 1
    )
    experiment.base_config = config
    started = []

    def api(path, payload=None):
        if path == "/api/session/state":
            return {"server_id": "server", "session_state": "ready"}
        if path == "/api/session/config":
            return config
        if path == "/api/session/messages":
            started.append(payload)
            return {}
        return {"runs": [{"id": "failed", "outcome": True}] if started else []}

    experiment.api = api
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        module, "summarize", lambda _: {"error": "workspace routing discovery failed"}
    )
    with pytest.raises(RuntimeError, match="subsequent trials stopped"):
        experiment.group("test", [(0, 0), (0, 1)], module.NATIVE)
    assert len(started) == 1
    assert json.loads((tmp_path / "test/results.json").read_text())[0]["error"]
