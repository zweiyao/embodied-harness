# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""The authored-tool freeze gate cannot silently test a changed candidate."""

import json

import pytest

from examples.univtac import freeze_authored_tool as module
from robots.libero.research.library import Library


@pytest.mark.parametrize(
    "case", ["no_gain", "different_tool", "different_budget", "valid"]
)
def test_freeze_checks_development_before_running_heldout(tmp_path, monkeypatch, case):
    dev = tmp_path / "dev"
    dev.mkdir()
    tool = {
        "name": "sensor_test",
        "description": "test",
        "source": "def run(frames, params): return {}",
        "parameters": {"type": "object"},
    }
    library = Library(tmp_path / "library")
    version = library.save([tool])
    config = dict.fromkeys(
        ("model", "reasoning_effort", "max_turns", "max_tokens", "planner_timeout_s"), 1
    )
    protocol = {"tool_version": version, "sources": {}, "base_config": config}
    evaluation = {
        "score": {
            "successes": 3,
            "trials": 3,
            "mean_total_tokens": 70 if case != "no_gain" else 110,
        },
        "baseline": {"mean_total_tokens": 100},
        "calls": {"valid_calls": 1},
    }
    for name, value in (
        ("protocol", protocol),
        ("evaluation", evaluation),
        ("candidate", tool),
    ):
        (dev / (name + ".json")).write_text(json.dumps(value))
    if case == "different_tool":
        tool["source"] += "\n# changed"
        (dev / "candidate.json").write_text(json.dumps(tool))
    calls = []

    class Experiment:
        def __init__(self, url, root):
            self.hashes = {}
            self.base_config = (
                {**config, "max_turns": 2} if case == "different_budget" else config
            )

        def group(self, label, trials, tools):
            calls.append((label, trials, tools))
            return [{"task": task, "seed": seed} for task, seed in trials]

        def status(self, **kwargs):
            pass

        def api(self, path, payload=None):
            return {"session_state": "ready"}

    monkeypatch.setattr(module, "Experiment", Experiment)
    monkeypatch.setattr(module, "score", lambda rows: {"trials": len(rows)})
    monkeypatch.setattr(
        module, "valid_tool_calls", lambda rows: {"valid_calls": len(rows)}
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "freeze",
            "--development",
            str(dev),
            "--output",
            str(tmp_path / "out"),
            "--library",
            str(tmp_path / "library"),
        ],
    )
    if case != "valid":
        with pytest.raises(ValueError):
            module.main()
        assert not calls
    else:
        module.main()
        assert len(calls) == 1
        assert calls[0][1] == [(t, s) for t in (1, 2) for s in range(5)]
        frozen = json.loads((tmp_path / "out/freeze.json").read_text())
        assert frozen["tool"] == tool and frozen["remote_maker_requests"] == 0
