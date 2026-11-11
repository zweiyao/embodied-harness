# 第一轮候选：身份一致、平移目标合成与真实夹爪反馈

状态：审批草稿；未修改经验库、工具源码、工具版本、运行材料、实验配置或原版 harness。本文不接入模型。它针对 20261109 Flash 三任务轨迹，不宣称已获得成功率收益。

## 最小范围

建议先经验-only，再相同经验加 A 的计算工具，必要时再加 B 的反馈变化；先验证机制，再决定是否合用，避免把一次成功归因于整组改动。

A：一篇短经验 + 已被模型采用的 sensor_patch_batch 新版本。优先验证任务 4 目标身份和相对量误用；不再新增一个重复的容器工具。

B：仅在选配 move_eef 的返回中增加实际夹爪反馈，再用同样的经验测试其采用和闭爪检查。原 move_to/move_pose/pi0_pick 实现和原版默认工具集保留。

任务 8 的语言与评分对象冲突已由实际50初态及相机投影确认，不能向经验写入固定方向来“修正”。修正版须单独批准和标记；原始结果保留。

## 拟修改文件

| 文件 | 具体变化 |
| --- | --- |
| `memory/libero/identity-and-transfer-evidence.md` | 新增下述 RPent 短经验；不重写现有经验正文。 |
| `memory/libero/MEMORY.md` | 加一条索引；现有条目保留。 |
| `examples/manual-workbench/sensor_patch_batch.py` | 增加可选 alignment_pair 模式；未提供时保留现有输出。 |
| `examples/manual-workbench/candidate.json` | 对应新参数、简短说明和 source；发布新不可变版本，不覆盖已发布版本。 |
| `tests/unit_tests/robots/libero/research/test_high_resolution.py` | 合成目标数学契约、步号及无效输入回归。 |
| `robots/libero/eef_control.py` | B 项：只增加 gripper command 与执行前后 qpos；不改控制步、限幅、容差或运动目标。 |
| `tests/unit_tests/robots/libero/test_eef_control.py` | B 项：反馈与真实执行次数一致；到位仍执行原有固定短步。 |
| `validation/qwen-continuous-20261109/` | 冻结包配置、哈希、实验计划和结果摘要。 |

独立候选运行材料为 `language-materials/qwen-evidence-v4/`。复制当前 v3 可读包；system/user/guide 原文不改。候选索引只包含原 next-action、原 grasp-feature 和新 identity-and-transfer 三篇，避免旧 object-relative-transfer 与新条目重复占用读取。原 v3 包不覆盖，所有原始记录保留。

## 新经验完整草稿

```markdown
# Keep object identity and transfer evidence consistent

- id: identity-and-transfer-evidence
- scope: libero
- kind: perception
- title: Keep object identity and transfer evidence consistent
- applies when: Selecting among similar objects or moving a visibly held object toward a goal.
- symptom: Checking the wrong object, changing the meaning of left/right, or confusing object-to-goal displacement with object-to-EEF offset.
- evidence:
  - cells: qwen-flash-eef-screen3-20261109/task4/seed0; qwen-flash-eef-screen3-20261109/task8/seed0
  - attempts: failed-trajectory review; task 8 benchmark has a language/goal inconsistency; only object-correspondence evidence used here
- confidence: mechanism supported; intervention benefit unvalidated
- related: next-action-evidence; grasp-feature-evidence

Keep the task's established viewpoint and the same object identity through selection, action and verification; robot axes do not rename the target. Verify the object actually acted on. After camera or object motion, locate the feature again; old pixels are not a track.

For a confirmed held object with unchanged orientation, align its visible point with the goal using the measured object-to-goal displacement. If available, use the tool's composed EEF target instead of treating that displacement as a grasp offset. Check returned images before lowering or releasing. Uncertain identity, occlusion, slipping or rotation invalidates this relation.

A motion returning at its target does not prove that the gripper closed. Check actual finger change and object motion; command execution, finger closure and holding are different claims.
```

全库 MEMORY.md 新增一行：

```markdown
- [identity-and-transfer-evidence.md](identity-and-transfer-evidence.md): Keep target identity and viewpoint consistent; distinguish transfer displacement, gripper execution and holding.
```

候选包 `memory/MEMORY.md` 完整替代文本：

```markdown
# LIBERO manipulation experience index

Read the entry matching the current unresolved decision. These are conditional hypotheses, not fixed trajectories or proof of success.

- [next-action-evidence.md](next-action-evidence.md): Before repeated localization, decide which evidence the next available primitive actually needs.
- [grasp-feature-evidence.md](grasp-feature-evidence.md): For a manual handle grasp, distinguish the handle from body, cavity and background; assess approach geometry and stalled motion.
- [identity-and-transfer-evidence.md](identity-and-transfer-evidence.md): Keep target identity and viewpoint consistent; distinguish transfer displacement, gripper execution and holding.
```

## A 项工具契约的具体前后

现在：`sensor_patch_batch(points, camera, step=-1, radius=2)` 返回各点的世界坐标和 EEF 相对量，模型自己重建合成动作目标。

候选：原参数仍可用；新增可选 `alignment_pair: [object_index, goal_index]`，指向当前 points 数组中两个不同点。点仍用现有 normalized [row,column]，不引入第二套像素坐标约定。只有启用此模式时必须显式给出最新非负 step，旧步号或 `-1` 返回 `alignment.status=refresh_required`，不生成目标。该门槛只验证帧来源；模型在新帧重用旧像素仍可能错误，不能把它当语义跟踪。

candidate.json 的 parameters.properties 新增：

```json
"alignment_pair": {
  "type": "array",
  "items": {"type": "integer", "minimum": 0, "maximum": 7},
  "minItems": 2,
  "maxItems": 2,
  "description": "Optional [held-object point index, goal point index] into points. Use a confirmed held object, unchanged orientation and an explicit latest step. Returns a conditional EEF target for XY alignment only; no lowering, collision or holding guarantee."
}
```

description 末尾新增两句：

> With alignment_pair, select one visible held-object point and one goal point in the same latest frame. The returned EEF target preserves height and orientation assumptions; it is a conditional point-alignment calculation, not a grasp, path or placement certificate.

合成仅在 pair 两点存在、不同、无逐点错误且 EEF 有限时发生；不设置臆造的抓稳阈值。核心计算完整如下（具体边界检查围绕此段，复用现有 schema 和逐点错误）：

```python
object_xyz = np.asarray(out[object_index]["world_median_xyz"])
goal_xyz = np.asarray(out[goal_index]["world_median_xyz"])
delta_xy = goal_xyz[:2] - object_xyz[:2]
target = eef.copy()
target[:2] += delta_xy
result["alignment"] = {
    "status": "computed_not_verified",
    "valid_at_step": frame["step"],
    "object_index": object_index,
    "goal_index": goal_index,
    "eef_target_xyz_keep_height": target.tolist(),
    "conditions": "Confirmed holding, unchanged orientation and correct same-frame point identities. Recheck images after motion; no vertical clearance or collision guarantee.",
}
```

已有 `patches` 完整保留用于检查，但不再要求模型用两个相似向量重新合成目标。`computed_not_verified` 不能升级成“可安全执行”或“任务成功”。此模式适用于可见目标点的平移对齐，包括盘面；原 `sensor_container_geometry` 仍仅按其已有开口适用范围使用，不能拿盘子内点或桌面稳定深度当篮筐内缘。

## B 项 EEF 反馈的具体前后

现在返回：真实执行 steps、目标与实测位姿、位姿残差、终止状态；工具外层 state 虽含 gripper_qpos，但核心动作结果不直接突出它。

候选在开始执行前读取机器人 raw_obs 的 gripper_qpos，并增加以下字段：

```python
"gripper_command": float(gripper),
"gripper_qpos_before": before_gripper_qpos,
"gripper_qpos_after": np.asarray(raw["robot0_gripper_qpos"]).tolist(),
"gripper_interpretation": "Finger motion only; neither closure nor object holding is certified.",
```

不添加“closed=true / grasped=true”，不改变控制器和固定短步循环。工具说明增加一句：

> Check returned finger positions and object motion; reaching the pose does not certify closure or holding.

若后续需要强制采用 move_eef、隐藏旧运动工具、引入新工作流或多 agent planner，应作为另一种实验条件，不能悄悄混入 A/B。

## 验证计划

1. 所有环境相关执行在远程。先对冻结语言包检查 source/hash、索引可读与写入拒绝，确认候选请求实际含正确工具版本与经验。
2. A 数学契约：当前 EEF、物体点与目标点整体平移时建议目标同移；交换 pair 方向结果反转；Z 保持原值；错索引、相同索引、坏点、旧步号和缺高分辨率数据都不生成 alignment 目标。默认不传 alignment_pair 的输出保持兼容。
3. A 历史帧回放：任务 4 对已人工核实的同帧点做直接函数与 Docker 两层回放，逐项对照 `eef + target - object`。不能只复用模型当轮误选的点作为“正确样例”；坏身份点应记录为语义未验证，不能因数值可算而报告通过。
4. B：在 fake 及已有 EEF 测试中检查实际步数与 qpos 前后值；包含已到位闭爪、提前终止、取消。需要真实动作检查时仅在另行批准的隔离仿真中做，不触碰真机。
5. 单独先筛任务 4：保持 Flash、600 秒、30 请求、16384 token、初态和工具集合一致，先 E，再 E+T，分别冻结版本；记录左右目标是否保持、alignment_pair 实际采用、错误量解释是否消失、官方成功和完整成本。B 单独确认反馈采用，不能把 A+B 合并的一次成功解释成 B 的收益。
6. 通过机制筛选后再按预先冻结的完整 10 任务计划与独立初态评测。一次成功只证明一次完成，不证明稳健性；不得筛掉模型有效失败。意外与正常预算失败继续沿用项目规则。

## 尚未解决的边界

- A 没有自动跟踪语义对象；它只减少已正确选点之后的量含义和代数负担。目标左右仍需任务/画面参照一致，任务 8 定义冲突必须独立处理。
- B 提高反馈显著性，尚未解决模型不选 move_eef；也不能保证指定短步足以闭爪。
- 任务 0 的指尖接触几何仍未确认，不能从 A/B 推断能修复全部空抓。
- 首轮不引入复杂多 agent 架构。若小改动不能修复对应机制，再以相同预算比较显式“识别—动作—验证”工作流，避免先增加协调开销而无法归因。

## 可直接审查的核心增量草稿

sensor_patch_batch.py 最后一个 `return {` 改为 `result = {`，原字典字段逐字保留；字典结束后追加以下完整逻辑：

```python
pair = params.get("alignment_pair")
if pair is not None:
    if step < 0 or frame["step"] != frames[-1]["step"]:
        result["alignment"] = {
            "status": "refresh_required",
            "reason": "Use an explicit latest step and reselect both points in its image.",
        }
    elif (
        not isinstance(pair, list)
        or len(pair) != 2
        or any(type(i) is not int or not 0 <= i < len(out) for i in pair)
        or pair[0] == pair[1]
    ):
        result["alignment"] = {
            "status": "invalid_pair",
            "reason": "Choose two different existing point indices: object, then goal.",
        }
    elif any("error" in out[i] for i in pair) or not np.isfinite(eef).all():
        result["alignment"] = {
            "status": "unavailable",
            "reason": "A selected surface or current EEF position is unavailable.",
        }
    else:
        object_index, goal_index = pair
        object_xyz = np.asarray(out[object_index]["world_median_xyz"])
        goal_xyz = np.asarray(out[goal_index]["world_median_xyz"])
        target = eef.copy()
        target[:2] += goal_xyz[:2] - object_xyz[:2]
        result["alignment"] = {
            "status": "computed_not_verified",
            "valid_at_step": frame["step"],
            "object_index": object_index,
            "goal_index": goal_index,
            "eef_target_xyz_keep_height": target.tolist(),
            "conditions": "Confirmed holding, unchanged orientation and correct same-frame point identities. Recheck images after motion; no vertical clearance or collision guarantee.",
        }
return result
```

move_eef 的动作输出增量（不是 move_pose 修改）：

```diff
         if p.env.terminated or p.env.truncated:
             return ToolResult(data={"error": "Environment episode ended"})
+        before_gripper_qpos = np.asarray(
+            p.env.raw_obs()["robot0_gripper_qpos"]
+        ).tolist()
         target = Rotation.from_quat(quat)
         executed = 0
@@
                 "steps_used": executed,
                 "max_steps": steps,
+                "gripper_command": float(gripper),
+                "gripper_qpos_before": before_gripper_qpos,
+                "gripper_qpos_after": np.asarray(
+                    raw["robot0_gripper_qpos"]
+                ).tolist(),
+                "gripper_interpretation": "Finger motion only; neither closure nor object holding is certified.",
                 "target_xyz": xyz.tolist(),
```

上述 diff 只对原本显式选配的 EEF 工具生效。测试 fake 需要提供与真实 raw_obs 相同的 gripper_qpos 字段。是否提高模型采用率与成功率仍需实际测试。
