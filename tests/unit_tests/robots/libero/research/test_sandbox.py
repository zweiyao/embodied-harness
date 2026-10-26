# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Opt-in local Docker boundary checks (no model or simulator required)."""

import os

import numpy as np
import pytest

from robots.libero.research.library import Sandbox

pytestmark = pytest.mark.skipif(
    os.environ.get("RPENT_RUN_SENSOR_SANDBOX") != "1",
    reason="requires the prebuilt local sensor Docker image",
)


@pytest.fixture
def sandbox():
    return Sandbox("embodied-sensor:pilot")


def run(sandbox, source, frames=None):
    return sandbox.run(
        {"parameters": {"type": "object"}, "source": source}, {}, frames or []
    )


def test_numpy_sensor_input(sandbox):
    result = run(
        sandbox,
        'import numpy as np\ndef run(frames, params): return {"mean": float(np.mean(frames[0]["depth"]))}',
        [{"depth": np.array([1.0, 2.0, 3.0])}],
    )
    assert result == {"mean": 2.0}


def test_finite_float_parameters_preserve_missing_sensor_values(sandbox):
    result = sandbox.run(
        {
            "parameters": {
                "type": "object",
                "properties": {"threshold": {"type": "number"}},
            },
            "source": 'import numpy as np\ndef run(frames, params): return {"threshold": params["threshold"], "missing": bool(np.isnan(frames[0]["depth"][0])), "mean": float(np.nanmean(frames[0]["depth"]))}',
        },
        {"threshold": 0.5},
        [{"depth": np.array([float("nan"), 1.0, 2.0])}],
    )
    assert result == {"threshold": 0.5, "missing": True, "mean": 1.5}


def test_no_host_files_writes_or_network(sandbox, tmp_path):
    secret = tmp_path / "private-evaluator.json"
    secret.write_text("private oracle")
    source = f"""import socket
from pathlib import Path
def run(frames, params):
    denied = []
    for operation in [lambda: Path({str(secret)!r}).read_text(), lambda: Path("/input/new").write_text("x"), lambda: socket.create_connection(("1.1.1.1", 80), .2)]:
        try:
            operation()
        except OSError:
            denied.append(True)
    return {{"denied": denied}}
"""
    assert run(sandbox, source) == {"denied": [True, True, True]}


def test_excessive_output_is_bounded(sandbox):
    with pytest.raises((ValueError, RuntimeError)):
        run(sandbox, 'def run(frames, params):\n    print("x" * 200000)\n    return {}')
