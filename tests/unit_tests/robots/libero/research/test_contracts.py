# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Offline contracts for the research boundary and library selection."""

from types import SimpleNamespace

import numpy as np
import pytest

from robots.libero.research.library import Library, validate_tools
from robots.libero.research.models import parse_json
from robots.libero.research.runner import accept_candidate, verify_splits
from robots.libero.research.sensors import PROPRIO, SensorInterface
from rpent.session import EnvState
from rpent.tools import ToolResult, tool


def candidate(source='def run(frames, params):\n    return {"count": len(frames)}'):
    return {
        "name": "sensor_count",
        "description": "Count frames",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "source": source,
    }


def test_library_versions_and_rollback(tmp_path):
    library = Library(tmp_path)
    empty = library.save([])
    version = library.save([candidate()])
    library.promote(version)
    library.promote(empty)
    assert library.load(version) == [candidate()]
    assert (tmp_path / "CURRENT").read_text().strip() == empty
    (tmp_path / f"{version}.json").write_text("[]")
    with pytest.raises(ValueError, match="hash"):
        library.load(version)


@pytest.mark.parametrize(
    "mutation",
    [
        {"name": "move_to"},
        {"source": "print('not a function')"},
        {
            "parameters": {
                "type": "object",
                "properties": {"x": {"$ref": "https://example.org/schema"}},
            }
        },
    ],
)
def test_rejects_invalid_declarations(mutation):
    definition = candidate()
    definition.update(mutation)
    with pytest.raises(ValueError):
        validate_tools([definition])


def test_validate_does_not_execute_source(tmp_path):
    source = f'open({str(tmp_path / "host-write")!r}, "w").write("bad")\ndef run(frames, params): return {{}}'
    validate_tools([candidate(source)])
    assert not (tmp_path / "host-write").exists()


def test_promotion_paired_no_regression():
    old = [
        {"task": 0, "seed": 2, "native_success": True},
        {"task": 3, "seed": 2, "native_success": False},
    ]
    better = [
        {"task": 0, "seed": 2, "native_success": True},
        {"task": 3, "seed": 2, "native_success": True},
    ]
    assert accept_candidate(old, better)
    assert not accept_candidate(old, old)
    assert not accept_candidate(old, list(reversed(old)))
    assert not accept_candidate(
        old, [better[0], {**better[1], "error": "runtime unavailable"}]
    )
    with pytest.raises(ValueError):
        accept_candidate(old, better[:1])


def test_splits_detect_seed_alias_and_identical_states():
    suite = SimpleNamespace(
        get_task_init_states=lambda task: np.array([[0], [1], [2]]),
        get_task=lambda task: SimpleNamespace(language="test instruction"),
    )
    config = {
        "tasks": [0],
        "splits": {"explore": [0], "validation": [1], "heldout": [2]},
    }
    assert len(verify_splits(config, suite)) == 3
    config["splits"]["heldout"] = [3]
    with pytest.raises(ValueError, match="repeated"):
        verify_splits(config, suite)
    suite.get_task_init_states = lambda task: np.zeros((4, 1))
    with pytest.raises(ValueError, match="repeated"):
        verify_splits(config, suite)


@pytest.fixture
def interface(tmp_path):
    state = EnvState(tmp_path)
    with state.record_step(
        state={
            **dict.fromkeys(PROPRIO, [0.0, 0.0, 0.0]),
            "object_names": ["hidden_object"],
        },
        terminated=True,
        truncated=False,
        command={"action": "hidden"},
        result={"success": True},
        extras={"task_language": "secret instruction"},
    ) as step:
        for camera in ("agentview", "wrist"):
            state.save(
                f"{camera}.png", np.zeros((256, 256, 3), dtype=np.uint8), step=step
            )
            state.save(f"{camera}_depth.npz", np.ones((256, 256)), step=step)
            state.save(f"{camera}_world.npz", np.zeros((256, 256, 3)), step=step)
            state.save(
                f"{camera}_metadata.json",
                {
                    "intrinsic_K": np.eye(3).tolist(),
                    "extrinsic_cam2world": np.eye(4).tolist(),
                    "hidden": "hidden_object",
                },
                step=step,
            )

    @tool
    def pi0_pick(prompt: str, max_chunks: int = 24, lift_thresh: float = 0.05):
        """Test controller."""
        return ToolResult(data={"success": True})

    @tool
    def read_text_file(path: str):
        """Privileged file read must not be exposed."""
        return ToolResult(data={"secret": True})

    calls = []

    def execute_tool(name, params):
        calls.append((name, params))
        with state.record_step(
            state=state.get().state,
            result={
                "success": True,
                "chunks_used": 24,
                "max_chunks": 24,
                "diagnostics": {"hidden": True},
            },
        ) as step:
            for camera in ("agentview", "wrist"):
                state.save(
                    f"{camera}.png", np.zeros((256, 256, 3), dtype=np.uint8), step=step
                )
        return ToolResult(data={"agent_elapsed_s": 1.0})

    toolkit = SimpleNamespace(
        state=state,
        list_tools=lambda: [pi0_pick, read_text_file],
        execute_tool=execute_tool,
    )
    api = SensorInterface(toolkit, [], None)
    return api, calls


def test_sensor_boundary_has_no_oracle_or_files(interface):
    import json

    api, _ = interface
    observed = api.observe()
    text = json.dumps(observed.data)
    assert "hidden" not in text and "success" not in text and "terminated" not in text
    assert len(observed.images) == 2
    assert "read_text_file" not in {t["name"] for t in api.declarations}
    assert api.execute("read_text_file", {"path": "/etc/passwd"}).is_error
    assert "hidden" not in str(api.execute("view_camera_meta", {}).data)
    assert "object_names" not in api.frames()[0]["proprio"]
    assert "hidden" not in api.frames()[0]["cameras"]["agentview"]["calibration"]


def test_controls_fixed_and_outputs_sanitized(interface):
    api, calls = interface
    assert api.execute("pi0_pick", {"prompt": "pick", "lift_thresh": 0}).is_error
    assert not calls
    result = api.execute("pi0_pick", {"prompt": "pick"})
    assert calls == [("pi0_pick", {"prompt": "pick"})]
    assert result.data["execution"] == {
        "chunks_used": 24,
        "max_chunks": 24,
        "chunk_budget_used": True,
    }
    assert "diagnostics" not in result.data
    assert api.execute("pi0_pick", {"prompt": "pick", "max_chunks": 3}).is_error
    schema = next(t for t in api.declarations if t["name"] == "pi0_pick")["parameters"]
    assert schema["properties"]["max_chunks"]["const"] == 24
    assert "success" not in result.data and "terminated" not in result.data


def test_json_protocol_rejects_prose():
    assert parse_json('```json\n{"tool":"finish"}\n```') == {"tool": "finish"}
    with pytest.raises(ValueError):
        parse_json("done")


def test_two_round_loop_promotes_then_rolls_back_and_holds_out(tmp_path, monkeypatch):
    import json
    import sys

    from robots.libero.research import runner
    from robots.libero.research.models import TEACHER_PROMPT

    suite = SimpleNamespace(
        get_task_init_states=lambda task: np.array([[0], [1], [2]]),
        get_task=lambda task: SimpleNamespace(language="task instruction"),
    )
    monkeypatch.setitem(
        sys.modules,
        "rlinf.envs.sim.libero.utils",
        SimpleNamespace(
            benchmark=SimpleNamespace(get_benchmark=lambda name: lambda: suite)
        ),
    )
    monkeypatch.setattr(
        runner, "Sandbox", lambda image: SimpleNamespace(image="fixed-image")
    )
    proposals, visited = [], []

    class FakeModel:
        def __init__(self, config):
            self.config = config

        def complete(self, system, payload, images):
            assert system == TEACHER_PROMPT
            assert all(
                row["seed"] != 2
                for row in payload["exploration"] + payload["incumbent_validation"]
            )
            if proposals:
                assert payload["previous_candidate_feedback"]["accepted"] is True
                assert payload["previous_candidate_feedback"]["tools"] == [candidate()]
            proposals.append(payload)
            source = (
                candidate()
                if len(proposals) == 1
                else candidate('def run(frames, params): return {"bad": True}')
            )
            return {"hypothesis": "test failure", "tools": [source]}, {}

    def fake_episode(config, cell, tools, model, sandbox, root):
        root.mkdir(parents=True)
        visited.append((cell["split"], model.config["model"], tools))
        return {
            "task": cell["task"],
            "seed": cell["seed"],
            "native_success": tools == [candidate()],
        }

    monkeypatch.setattr(runner, "init_output_dir", lambda root: root)
    monkeypatch.setattr(runner, "Model", FakeModel)
    monkeypatch.setattr(runner, "episode", fake_episode)
    config = {
        "suite": "fake",
        "libero_type": "pro",
        "tasks": [0],
        "splits": {"explore": [0], "validation": [1], "heldout": [2]},
        "sandbox_image": "fake",
        "library_dir": str(tmp_path / "library"),
        "teacher": {"model": "teacher"},
        "actor": {"model": "actor"},
        "iterations": 2,
    }
    runner.run(config, tmp_path / "development")
    summary = json.loads((tmp_path / "development/summary.json").read_text())
    assert [r["accepted"] for r in summary["rounds"]] == [True, False]
    assert all(split != "heldout" for split, _, _ in visited)
    assert Library(tmp_path / "library").load(summary["version"]) == [candidate()]
    runner.run(config, tmp_path / "paused", stop_after_baseline=True)
    assert (tmp_path / "paused/pause.json").is_file()
    assert len(proposals) == 2
    config["start_version"] = summary["version"]
    visited.clear()
    runner.run(config, tmp_path / "holdout", heldout=True)
    assert len(proposals) == 2
    assert len(visited) == 2
    assert all(split == "heldout" and model == "actor" for split, model, _ in visited)


def test_library_has_no_three_tool_limit(tmp_path):
    tools = [{**candidate(), "name": f"sensor_tool_{i}"} for i in range(5)]
    library = Library(tmp_path)
    assert library.load(library.save(tools)) == tools


def test_reuse_baseline_checks_identity_and_excludes_private_state(tmp_path):
    import json

    from robots.libero.research.runner import reuse_baseline

    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    protocol = {"config_sha256": "fixed", "controller_sha256": "fixed"}
    cells = [
        {"task": 0, "seed": seed, "split": split, "initial_state_sha256": str(seed)}
        for seed, split in enumerate(("explore", "validation"))
    ]
    config = {"teacher": {"model": "teacher"}, "actor": {"model": "actor"}}
    for name, data in (
        ("pause", {"phase": "baseline_complete"}),
        ("protocol", protocol),
        ("splits", cells),
    ):
        (source / f"{name}.json").write_text(json.dumps(data))
    for seed, label, model in (
        (0, "teacher-explore", "teacher"),
        (1, "baseline", "actor"),
    ):
        rows = [
            {
                "task": 0,
                "seed": seed,
                "model": model,
                "library": "version",
                "initial_state_sha256": str(seed),
            }
        ]
        (source / f"{label}.json").write_text(json.dumps(rows))
        directory = source / label / f"t0-s{seed}"
        directory.mkdir(parents=True)
        (directory / "initial-0.png").write_bytes(b"sensor image")
        (directory / "private-state.json").write_text("oracle")
    exploration, baseline = reuse_baseline(
        source, destination, protocol, cells, "version", config
    )
    assert exploration[0]["model"] == "teacher" and baseline[0]["model"] == "actor"
    assert (
        destination / "baseline/t0-s1/initial-0.png"
    ).read_bytes() == b"sensor image"
    assert not list(destination.rglob("private-state*"))
    with pytest.raises(ValueError, match="protocol changed"):
        reuse_baseline(
            source,
            tmp_path / "bad",
            {**protocol, "controller_sha256": "changed"},
            cells,
            "version",
            config,
        )
    with pytest.raises(ValueError, match="incompatible"):
        reuse_baseline(
            source, tmp_path / "bad", protocol, cells, "other-version", config
        )


def test_segment_point_and_overlay_reuse_rpent(interface):
    import base64
    import io

    import imageio.v2 as imageio

    from rpent.robots.components.sam3_client import Sam3Client

    api, _ = interface
    mask = np.zeros((256, 256), dtype=np.uint8)
    mask[10:20, 30:40] = 255
    buffer = io.BytesIO()
    imageio.imwrite(buffer, mask, format="png")
    calls = []

    def rpc(method, *, kwargs, timeout_s):
        calls.append(kwargs)
        return {
            "found": True,
            "score": 0.9,
            "box": [30, 10, 40, 20],
            "mask_shape": [256, 256],
            "mask_png_base64": base64.b64encode(buffer.getvalue()).decode(),
        }

    api.toolkit.primitives = SimpleNamespace(
        _sam3_client=Sam3Client(SimpleNamespace(call=rpc))
    )
    assert api.execute("segment", {}).is_error
    assert api.execute("segment", {"prompt": "can", "point": [15, 35]}).is_error
    assert not calls
    result = api.execute("segment", {"point": [15, 35]})
    assert not result.is_error
    assert calls[0]["point"] == [15, 35] and "text_prompt" not in calls[0]
    assert result.data["point"] == [15, 35]
    assert len(result.images) == 1
    overlay = imageio.imread(io.BytesIO(result.images[0]))
    assert overlay[15, 35, 0] > 0 and not overlay[0, 0].any()
    assert api.frames()[0]["masks"]["m0"]["mask"][15, 35]
