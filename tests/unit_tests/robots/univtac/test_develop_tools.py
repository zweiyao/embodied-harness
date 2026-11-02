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
    assert not module.early_stop(candidate, base, {**judge, "success_benefit": False})
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


def test_five_optimizations_then_frozen_test_without_test_feedback(
    tmp_path, monkeypatch
):
    calls = []

    class FakeExperiment:
        def __init__(self, url, root):
            self.hashes, self.base_config = {}, {}

        def api(self, path, payload=None):
            return (
                {"session_state": "ready"}
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
                    **row(tokens=100 if label == "development-baseline" else 90),
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
        if schema == module.JUDGE_SCHEMA:
            return {
                "token_benefit": True,
                "success_benefit": False,
                "stop_recommended": False,
                "reason": "not enough evidence",
            }
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
        ],
    )
    module.main()
    assert len(makers) == 5
    assert len(calls) == 7  # baseline, five revisions, frozen evaluation
    assert all(task == 0 for _, trials, _ in calls[:-1] for task, _ in trials)
    assert calls[-1][1] == [(task, seed) for task in (1, 2) for seed in range(5)]
    assert len([name for name in calls[-1][2] if name.startswith("generated:")]) == 1
    assert (tmp_path / "experiment/freeze.json").exists()
