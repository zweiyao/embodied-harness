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


@pytest.mark.parametrize("planner_view_mode", ["native", "calibrated-pair-v1"])
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
    tmp_path,
    monkeypatch,
    fake_single_arm_primitives,
    motion,
    invalid_eef,
    planner_view_mode,
):
    from rpent.utils import templates

    monkeypatch.setattr(
        templates, "default_variables", lambda: {"output_dir": str(tmp_path)}
    )
    names = {motion, "finish"} | (
        {"move_eef"} if invalid_eef and motion != "rotate_axis" else set()
    )
    if planner_view_mode != "native":
        names |= {"view_env_state", "read_image"}
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
            for name, size in (
                ("agentview_policy.png", 16),
                ("agentview_high.png", 32),
                ("wrist_high.png", 24),
            ):
                state.save(
                    name, np.full((size, size, 3), size, dtype=np.uint8), step=step
                )
        return state.get(step)

    monkeypatch.setattr(libero.libero_tools, "dump_state", dump)
    journal = RunJournal(tmp_path / "state")
    arguments = {
        "planner_view_mode": planner_view_mode,
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
    if planner_view_mode == "native":
        assert len(result.images) == 3
        assert "image_views" not in result.data
    else:
        assert [v["artifact"] for v in result.data["image_views"]] == [
            "agentview_high.png",
            "wrist_high.png",
        ]
        assert [v["width"] for v in result.data["image_views"]] == [32, 24]
        assert all(v["step"] == 1 for v in result.data["image_views"])
        assert result.images == [
            t.state.load_bytes(v["artifact"], step=1)
            for v in result.data["image_views"]
        ]
    if planner_view_mode == "native":
        assert t.execute_tool("view_env_state", {}).is_error
    else:
        viewed = t.execute_tool("view_env_state", {"step": 1})
        assert viewed.images == result.images
        assert viewed.data["image_views"] == result.data["image_views"]
        assert (
            t.execute_tool(
                "read_image", {"name": "agentview_policy.png", "step": 0}
            ).data["image_views"][0]["coordinate_frame"]
            == "policy"
        )
        assert t.state.latest_record().step_idx == 1
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


@pytest.fixture
def presentation(tmp_path):
    from rpent.session import EnvState

    store = EnvState(tmp_path)
    for index in range(2):
        with store.record_step(state={"fixture": index}, terminated=False) as step:
            for name, shape in [
                ("agentview_policy.png", (8, 8)),
                ("agentview.png", (12, 10)),
                ("agentview_high.png", (24, 30)),
                ("wrist_high.png", (20, 28)),
                ("overlay.png", (14, 16)),
            ]:
                store.save(
                    name,
                    np.full((*shape, 3), index * 50 + shape[0], np.uint8),
                    step=step,
                )
    instance = ManualToolkit.__new__(ManualToolkit)
    instance._state = store
    instance.planner_view_mode = "calibrated-pair-v1"
    return instance


@pytest.mark.parametrize("step", [0, -1])
def test_explicit_view_preserves_bytes_state_and_resolved_step(presentation, step):
    from robots.libero.tools import view_env_state

    t = presentation
    original = view_env_state(step=step, state=t.state)
    actual = t._planner_view(lambda **kwargs: original, step=step)
    expected_step = 0 if step == 0 else 1
    assert {k: actual.data[k] for k in original.data} == original.data
    assert actual.images == [
        t.state.load_bytes(name, step=expected_step)
        for name in ("agentview_high.png", "wrist_high.png")
    ]
    assert actual.data["image_views"] == [
        {
            "index": 0,
            "artifact": "agentview_high.png",
            "camera": "agentview",
            "step": expected_step,
            "width": 30,
            "height": 24,
            "coordinate_frame": "calibrated",
        },
        {
            "index": 1,
            "artifact": "wrist_high.png",
            "camera": "wrist",
            "step": expected_step,
            "width": 28,
            "height": 20,
            "coordinate_frame": "calibrated",
        },
    ]
    t.planner_view_mode = "native"
    assert t._present_state(original) is original
    assert t.state.latest_record().step_idx == 1  # Explicit reads never capture a step.
    error = view_env_state(step=99, state=t.state)
    t.planner_view_mode = "calibrated-pair-v1"
    assert t._present_state(error) is error and error.is_error


@pytest.mark.parametrize(
    "name,frame,camera",
    [
        ("agentview_policy.png", "policy", "agentview"),
        ("agentview.png", "calibrated", "agentview"),
        ("wrist_high.png", "calibrated", "wrist"),
        ("overlay.png", "unclassified", None),
    ],
)
def test_explicit_reader_does_not_substitute_or_mislabel(
    presentation, name, frame, camera
):
    t = presentation
    actual = t.read_image(name=name, step=0)
    assert actual.images == [t.state.load_bytes(name, step=0)]
    assert actual.data["image_views"][0]["coordinate_frame"] == frame
    assert actual.data["image_views"][0]["camera"] == camera
    assert actual.data["image_views"][0]["step"] == 0
    assert t.read_image(name="unknown.png").is_error
    t.planner_view_mode = "native"
    old = t.read_image(name=name, step=0)
    assert old.data == {"artifact": name, "step": 0}
    assert old.images == actual.images


@pytest.mark.parametrize("name", ["agentview_high.png", "wrist_high.png"])
@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_required_image_is_explicit_not_partial(presentation, name, corrupt):
    from robots.libero.tools import view_env_state

    t = presentation
    path = t.state.artifact_path(name, step=1)
    if corrupt:
        path.write_bytes(b"unreadable fixture")
    else:
        path.unlink()
    old = view_env_state(step=1, state=t.state)
    actual = t._present_state(old)
    assert actual.is_error and name in actual.data["error"]
    assert actual.images == [] and actual.data["image_views"] == []
    assert actual.data["step"] == 1
    t.planner_view_mode = "native"
    assert t._present_state(old) is old


def test_manual_factory_receives_only_explicit_view_mode(tmp_path, monkeypatch):
    from robots.libero.robot_spec import get_toolkit

    config = SimpleNamespace(
        prompt_vars={
            "manual_tools": [],
            "run_journal": object(),
            "memory_dir": str(tmp_path / "memory"),
        },
        output_dir=tmp_path,
        enable_direct_action=False,
    )
    monkeypatch.setattr(
        "robots.libero.research.manual.ManualToolkit", lambda **kwargs: kwargs
    )
    default = get_toolkit(runtime_kwargs={}, dashboard_events=None, config=config)
    assert "planner_view_mode" not in default
    config.prompt_vars["planner_view_mode"] = "calibrated-pair-v1"
    assert (
        get_toolkit(runtime_kwargs={}, dashboard_events=None, config=config)[
            "planner_view_mode"
        ]
        == "calibrated-pair-v1"
    )
