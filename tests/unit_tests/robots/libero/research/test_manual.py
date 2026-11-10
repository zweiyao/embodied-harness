# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Selection must constrain dispatch while preserving native control schemas."""

from types import SimpleNamespace

import numpy as np
import pytest

from robots.libero import toolkit as libero
from robots.libero.research.manual import ManualToolkit
from rpent.dashboard.workbench import RunJournal, native_catalog
from rpent.memory import MemoryManager
from rpent.tools import ToolResult


@pytest.mark.parametrize(
    "motion, invalid_eef",
    [
        ("pi0_pick", False),
        ("translate_to", False),
        ("translate_to", True),
        ("align_placement", False),
        ("rotate_axis", False),
        ("rotate_axis", True),
    ],
)
def test_native_controls_unchanged_and_disabled_tool_rejected(
    tmp_path, monkeypatch, fake_single_arm_primitives, motion, invalid_eef
):
    from rpent.utils import templates

    monkeypatch.setattr(
        templates, "default_variables", lambda: {"output_dir": str(tmp_path)}
    )
    names = {motion, "finish"} | (
        {"move_eef"} if invalid_eef and motion != "rotate_axis" else set()
    )
    if motion == "align_placement":
        names.add("preview_placement")
    selected = [t for t in native_catalog() if t["name"] in names]
    fake = fake_single_arm_primitives.for_robot(libero.libero_tools.LiberoPrimitives)
    fake.env = SimpleNamespace(terminated=False, truncated=False)
    if invalid_eef:
        fake.env.get_eef_controller_state = lambda: {
            "error": "unsupported fixture controller"
        }
    fake._sam3_client = None
    calls = []
    if motion == "rotate_axis":
        from robots.libero.research.orientation import OrientationControl

        if not invalid_eef:
            fake.env.get_eef_controller_state = lambda: {}

        def rotate(self, axis, angle_rad):
            calls.append({"axis": axis, "angle_rad": angle_rad})
            return ToolResult(data={"steps_used": 10, "gripper_command": 0.0})

        monkeypatch.setattr(
            OrientationControl,
            "rotate_axis",
            OrientationControl.rotate_axis.with_handler(rotate),
        )

    def pick(self, **kwargs):
        calls.append(kwargs)
        return ToolResult(data={"chunks_used": 1})

    fake.pi0_pick = libero.libero_tools.LiberoPrimitives.pi0_pick.with_handler(pick)

    def move(self, xyz, **kwargs):
        calls.append({"xyz": xyz, **kwargs})
        return ToolResult(data={"steps_used": 1})

    fake.move_to = libero.libero_tools.LiberoPrimitives.move_to.with_handler(move)
    monkeypatch.setattr(libero.libero_tools, "LiberoPrimitives", fake)

    def dump(primitives, state, log):
        log = log or {}
        with state.record_step(
            state={},
            terminated=False,
            command=log.get("command"),
            result=log.get("result"),
            extras={"task_language": "fixture"},
        ) as step:
            for camera in ("agentview", "wrist"):
                state.save(
                    camera + ".png", np.zeros((256, 256, 3), dtype=np.uint8), step=step
                )
        return state.get(step)

    monkeypatch.setattr(libero.libero_tools, "dump_state", dump)
    journal = RunJournal(tmp_path / "state")
    arguments = {
        "selected": selected,
        "journal": journal,
        "runtime_kwargs": {},
        "dashboard_events": SimpleNamespace(enabled=False, emit=lambda x: None),
        "memory": MemoryManager(tmp_path / "memory"),
        "state_output_dir": tmp_path / "state",
    }
    if invalid_eef:
        with pytest.raises(ValueError, match="unsupported fixture controller"):
            ManualToolkit(**arguments)
        assert not calls
        return
    t = ManualToolkit(**arguments)
    assert {x.name for x in t.list_tools()} == names
    assert t.execute_tool("move_to", {"target": [0, 0, 0]}).is_error
    assert t.execute_tool("segment", {"prompt": "can"}).is_error
    if motion == "pi0_pick":
        result = t.execute_tool(motion, {"prompt": "pick", "max_chunks": 3})
        assert calls[0]["max_chunks"] == 3
    elif motion == "align_placement":
        from tests.unit_tests.robots.libero.research.test_placement import observation

        frame, params = observation()
        t.sensors.frames = lambda: [frame]
        fake.env.raw_obs = lambda: frame["proprio"]
        preview = t.execute_tool("preview_placement", params)
        assert len(preview.images) == 2
        result = t.execute_tool(motion, {"preview_id": preview.data["preview_id"]})
        assert calls == [
            {"xyz": preview.data["eef_target_xyz_keep_height"], "gripper": 0.0}
        ]
        assert t.state.latest_record().command["action"] == "align_placement"
        assert (
            t.state.latest_record().result["preview_id"] == preview.data["preview_id"]
        )
    elif motion == "rotate_axis":
        result = t.execute_tool(motion, {"axis": "z", "angle_rad": 0.08})
        assert calls == [{"axis": "z", "angle_rad": 0.08}]
        assert t.state.latest_record().command["action"] == "rotate_axis"
        assert t.state.latest_record().result["gripper_command"] == 0.0
        assert t.execute_tool("rotate_wrist", {"delta_yaw": 0.08}).is_error
    else:
        result = t.execute_tool(motion, {"xyz": [0.1, 0.2, 0.3]})
        assert calls == [{"xyz": [0.1, 0.2, 0.3], "gripper": 0.0}]
        assert t.state.latest_record().command["action"] == "translate_to"
        assert t.state.latest_record().result["gripper_command"] == 0.0
    assert len(result.images) == 2
    assert t.execute_tool("view_env_state", {}).is_error
    t.close()


def test_api_and_mcp_discover_the_same_selected_tools(tmp_path, monkeypatch):
    from rpent.planner.api_loop import _HarnessToolkit
    from rpent.tools import tool
    from rpent.utils import templates

    monkeypatch.setattr(
        templates, "default_variables", lambda: {"output_dir": str(tmp_path)}
    )

    @tool(readonly=True)
    def sensor_probe() -> ToolResult:
        """Probe."""
        return ToolResult(data={})

    @tool(readonly=True)
    def finish(status: str, summary: str) -> ToolResult:
        """Finish."""
        return ToolResult(data={"_finish": True})

    selected = SimpleNamespace(
        planner_tools_only=True, list_tools=lambda: (sensor_probe, finish)
    )
    adapter = _HarnessToolkit(
        selected, dashboard_events=SimpleNamespace(enabled=False), no_images=False
    )
    assert set(adapter.validators) == {t.name for t in selected.list_tools()}
    assert set(adapter.tools) == {"sensor_probe"}  # finish is the API output tool
    assert "read_image" not in adapter.tools


def test_segment_mask_is_aligned_and_original_result_preserved(tmp_path):
    import threading

    from rpent.session import EnvState

    store = EnvState(tmp_path)
    with store.record_step(state={}, terminated=False) as step:
        store.save("agentview.png", np.zeros((256, 256, 3), dtype=np.uint8), step=step)
        store.save(
            "agentview_high.png", np.zeros((1024, 1024, 3), dtype=np.uint8), step=step
        )
    instance = ManualToolkit.__new__(ManualToolkit)
    instance._state = store
    instance.mask_lock = threading.RLock()
    instance.mask_client = SimpleNamespace(local=SimpleNamespace(result=None))
    instance.sensors = SimpleNamespace(masks={})
    result = ToolResult(
        data={
            "step": 0,
            "camera": "agentview",
            "image_artifact": "agentview_high.png",
            "segment_artifact": "segment_00.json",
            "world_xyz": [1, 2, 3],
        }
    )
    mask = np.zeros((1024, 1024), dtype=bool)
    mask[400:600, 400:600] = True

    def original(**kwargs):
        instance.mask_client.local.result = SimpleNamespace(found=True, mask=mask)
        store.save(
            "segment_00.json",
            {
                "mode": "text",
                "prompt": "bottle",
                "camera": "agentview",
                "segment_index": 0,
            },
            step=0,
        )
        return result

    assert instance.segment_recorded(original) is result
    aligned = instance.sensors.masks[0]["segment_00_mask.npz"]["mask"]
    assert aligned.shape == (256, 256)
    assert aligned[125, 125] and not aligned[0, 0]
    assert store.load("segment_00_mask.npz", step=0).shape == (1024, 1024)
    assert (
        store.load("mask_alignment_segment_00.json", step=0)["source_artifact"]
        == "agentview_high.png"
    )
    # Auxiliary metadata must not be mistaken for native segment commands.
    with store.record_step(state={}, terminated=True):
        pass
    recipe = libero.libero_tools.write_recipe_from_states(
        store, "fixture", output_dir=tmp_path
    )
    import json

    assert [
        json.loads(line) for line in (tmp_path / recipe).read_text().splitlines()
    ] == [{"action": "segment", "prompt": "bottle", "camera": "agentview"}]


def test_generated_omitted_optional_parameters_are_not_sent_to_sandbox():
    import threading

    from jsonschema import Draft202012Validator

    from robots.libero.research.native import _arguments_model

    schema = {
        "type": "object",
        "properties": {"step": {"type": "integer", "default": -1}},
        "additionalProperties": False,
    }
    instance = ManualToolkit.__new__(ManualToolkit)
    instance.mask_lock = threading.RLock()
    instance.sensors = SimpleNamespace(frames=lambda: [])
    logged = []
    instance.journal = SimpleNamespace(append=lambda k, v: logged.append(v))

    def execute(definition, params, frames):
        Draft202012Validator(schema).validate(params)
        return {"step": params.get("step", -1)}

    instance.sandbox = SimpleNamespace(image="fixture", run=execute)
    model = _arguments_model("OptionalStep", schema)
    for supplied, expected in [({}, -1), ({"step": 0}, 0)]:
        args = model.model_validate(supplied)
        kwargs = {key: getattr(args, key) for key in type(args).model_fields}
        result = instance.generated({"name": "sensor_fixture"}, **kwargs)
        assert result.data == {"step": expected}
        assert logged[-1]["params"] == supplied


@pytest.mark.parametrize("name", ["preview_placement", "align_placement"])
def test_incomplete_placement_pair_fails_before_environment_initialization(
    monkeypatch, name
):
    initialized = []
    monkeypatch.setattr(
        libero.LiberoToolkit, "__init__", lambda *a, **k: initialized.append(True)
    )
    selected = [t for t in native_catalog() if t["name"] in {name, "finish"}]
    with pytest.raises(ValueError, match="together"):
        ManualToolkit(selected=selected, journal=None)
    assert not initialized
