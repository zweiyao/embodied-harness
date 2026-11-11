# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read-only Flexiv tool descriptions using the same registration declarations."""

import hashlib
import inspect
import json
from pathlib import Path

from robots.flexiv.toolkit import FlexivToolkit, tool_methods
from rpent.tools import Tool, iter_tools
from rpent.tools.common import CommonTools


def generated_availability(item: dict) -> tuple[bool, str | None]:
    """Check whether a generated declaration has a supported recorded-input adapter."""
    adapter = item.get("input_adapter")
    if adapter is None and item["name"] == "sensor_alignment_contact":
        # The first published version predates explicit input-adapter metadata.
        adapter = "flexiv.alignment.v1"
    if adapter not in {"flexiv.alignment.v1", "flexiv.visual_alignment.v1"}:
        return False, "尚无此工具的 Flexiv 观测适配器。"
    fields = {
        "anchor_step",
        "feature_record",
        "reference_records",
        "compare_steps",
        "track_with_tcp",
    }
    if adapter == "flexiv.visual_alignment.v1":
        fields = {
            "anchor_step",
            "compare_steps",
            "camera",
            "feature_axis_px",
            "reference_axis_px",
        }
    schema = item.get("parameters", {})
    optional = {"reselected_axes"} if adapter == "flexiv.visual_alignment.v1" else set()
    if (
        set(schema.get("properties", {})) != fields | optional
        or set(schema.get("required", [])) != fields
    ):
        return False, "工具参数与 Flexiv 对齐／接触观测适配器不匹配。"
    return True, None


def catalog(
    *,
    control_mode: str = "native",
    declarations: tuple[Tool, ...] | None = None,
    library_root: str | Path | None = None,
) -> list[dict]:
    """Describe supported and registered tools without opening an environment."""
    active = (
        None if declarations is None else {tool.name: tool for tool in declarations}
    )
    owners = [
        (getattr(FlexivToolkit, name), False)
        for name in tool_methods(None, control_mode)
    ]
    owners += [(tool, True) for tool in iter_tools(CommonTools)]
    result = []
    for supported, common in owners:
        tool = supported if active is None else active.get(supported.name, supported)
        source = inspect.getsource(tool.handler)
        category = (
            "auxiliary" if common else "perception" if tool.readonly else "control"
        )
        availability = (
            "conditional"
            if active is None
            else "registered"
            if tool.name in active
            else "not_registered"
        )
        note = {
            "registered": "本轮已注册；执行仍遵循当前机械臂状态。",
            "not_registered": "本轮未注册，模型不能通过 RPent 调用。",
            "conditional": "此模式支持；任务启动时按启用状态和标定配置注册。",
        }[availability]
        result.append(
            {
                "id": "native:" + tool.name,
                "name": tool.name,
                "origin": "native",
                "category": category,
                "description": tool.description,
                "parameters": tool.input_schema,
                "version": hashlib.sha256(source.encode()).hexdigest(),
                "source": source,
                "required": tool.name == "finish",
                "dependencies": [],
                "validation": "native",
                "availability": availability,
                "availability_note": note,
                "input_contract": {
                    "tactile_compare": (
                        "输入两个已有观测步骤编号，读取左指原始触觉图像及元数据。"
                        "返回原图像素位移和跟踪质量；图像 x 向右、y 向下，"
                        "没有基座坐标或牛顿力标定。参考帧不假定为空载。"
                    ),
                    "move_eef_delta": (
                        "相对当前实测 TCP：translation_m=[dx,dy,dz]，基座轴方向，米；"
                        "rotation_vector_rad=[rx,ry,rz]，基座轴方向的旋转向量"
                        "（单位轴×旋转角，弧度），不是欧拉角或四元数。"
                        "例如 [0,0,0.08726646] 表示绕基座 +Z 旋转 5°。"
                        "增量只应用一次；执行时长见参数声明。"
                    ),
                    "move_tcp": (
                        "绝对 TCP 目标：position_m=[x,y,z]，基座坐标，米；"
                        "quaternion_wxyz=[w,x,y,z] 为目标姿态单位四元数。"
                        "省略姿态时保持当前姿态。"
                    ),
                    "move_eef": (
                        "绝对 TCP 目标：position_m=[x,y,z]，基座坐标，米；"
                        "quaternion_wxyz=[w,x,y,z] 为目标姿态单位四元数；"
                        "steps 指向同一目标的短程控制次数，不保证到位。"
                    ),
                }.get(tool.name, "具体输入、单位与执行方式见参数声明。"),
                "example": None,
            }
        )
    if library_root is not None:
        from robots.libero.research.library import Library

        root = Path(library_root)
        if not root.is_dir():
            raise ValueError("Configured Flexiv tool library does not exist")
        library = Library(root)
        for path in sorted(root.glob("*.meta.json")):
            version = path.name.removesuffix(".meta.json")
            metadata = json.loads(path.read_text())
            (tool,) = library.load(version)
            supported, reason = generated_availability({**metadata, **tool})
            result.append(
                {
                    **metadata,
                    **tool,
                    "id": "generated:" + version,
                    "origin": "generated",
                    "category": "perception",
                    "version": version,
                    "required": False,
                    "availability": (
                        "conditional"
                        if supported and active is None
                        else "registered"
                        if supported and tool["name"] in active
                        else "not_registered"
                        if supported
                        else "candidate"
                    ),
                    "availability_note": reason
                    or "可由本轮选择启用；读取记录帧并在隔离容器中执行。回放通过不代表任务效果提升。",
                }
            )
    return sorted(result, key=lambda item: (item["category"], item["name"]))
