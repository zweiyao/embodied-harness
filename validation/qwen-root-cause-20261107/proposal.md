# Qwen 感知判断优化草案（待批准，未接入运行环境）

## 批准范围

建议批准下述两个独立语言材料副本、两条经验和 10 轮小样本筛选。
不改原版 system/user/guide、原始经验、原生工具实现和在线工作台默认配置。
不把本文作为运行时提示词。实验结束恢复临时服务并核对保护文件哈希。
新的工具实现仅列为后续设计方向，不包含在本轮实施申请中。

## 文件与配置的具体变化

拟新增远程目录（本地保留对应可审查版本）：

- `language-materials/qwen-evidence-v2-text/`：从 `qwen-minimal-v1` 复制，新增下面两篇经验，修改该副本的 `memory/MEMORY.md`。
- `language-materials/qwen-evidence-v2-tools/`：与 text 版的所有语言材料字节一致。
- `experiments/qwen-evidence-v2-screening/plan.json` 与隔离运行配置：保存冻结材料哈希、工具版本、任务/seed、预算和分组。脚本复用已验证的隔离运行与意外重跑机制。
- Git 中保存对应经验源文件、计划和验证摘要；生成的运行材料副本不覆盖 `language-materials/v1` 或 `qwen-minimal-v1`。

两个副本的 `MEMORY.md` 在现有条目之前新增，原有条目不重写：

```markdown
- [libero/next-action-evidence.md](libero/next-action-evidence.md): Choose the next primitive and resolve only its missing evidence; relevant when localization continues without action.
- [libero/object-relative-transfer.md](libero/object-relative-transfer.md): Separate holding evidence, object placement geometry and observed motion; relevant to grasp-and-transfer failures.
```

系统提示词、用户提示词、指南的前后内容完全一致，沿用已获批的简短提示版本。
两组唯一配置差别是可用的工具列表：

```text
text:  原有 17 个 native 工具
tools: 原有 17 个 native 工具
       + sensor_patch_batch @ cca2f3c424d195fe3e55896ec0fe4c54b08b9f6929fdf794cfc98595458155c3
       + sensor_container_geometry @ 2e120f1952a10536ded83dc85a9a78506db0f6e4c80efc741b8cfa28680b0829
```

工具引用按现有注册接口生成；先验证选中版本与实际渲染声明，不猜测引用字符串。
这两份现有实现不修改、不重新发布。它们已经封装批量反投影、稳健统计、末端偏移、内缘多边形和物体采样点相对开口的关系。
容器工具只适用于可见、近水平的开放容器，不用于盘子、抽屉或完整物体位姿估计。

## 新文件完整草稿：memory/libero/next-action-evidence.md

```markdown
# Resolve evidence for the next primitive

- id: next-action-evidence
- scope: libero
- kind: planning
- title: Resolve evidence for the next primitive
- applies when: LIBERO offers a learned pick primitive and localization continues before manipulation.
- symptom: Repeated geometry queries on an unchanged scene without starting an action.
- evidence:
  - cells: libero10-task-no-memory-dual-20-20261107/qwen/task4/seed0; libero10-task-no-memory-dual-20-20261107/qwen/task3/seed0; e0994d4389f86809f327
  - attempts: historical trajectory review
- confidence: hypothesis; task benefit unvalidated
- related: object-relative-transfer

Choose the next primitive before measuring. Query only a fact whose answer could change that action. A learned pick needs an unambiguous target description, not a manually reconstructed grasp pose. If identity and access are sufficiently supported, try the primitive and inspect its feedback. Resolve a specific ambiguity when they are not. Defer later placement geometry until needed; reuse geometry only while its object and scene relation remain unchanged.

Fails when the primitive cannot reach the target, the target is ambiguous or occluded, or relevant geometry has changed. Earlier action alone does not establish success.
```

## 新文件完整草稿：memory/libero/object-relative-transfer.md

```markdown
# Separate object evidence from end-effector geometry

- id: object-relative-transfer
- scope: libero
- kind: perception
- title: Separate object evidence from end-effector geometry
- applies when: Grasping and transferring a visible object with LIBERO manipulation primitives.
- symptom: Repeated alignment, uncertain grasp, or an end effector above a goal without completed placement.
- evidence:
  - cells: d50624cbffb925e23222; a36a0500616f1edae655; libero10-task-no-memory-dual-20-20261107/qwen/task2/seed0
  - attempts: historical trajectory review
- confidence: hypothesis; task benefit unvalidated
- related: next-action-evidence

Check target identity and holding evidence separately from a pick heuristic. For an open container, measure its visible inner rim and a visible point on the held object; compare the object with the opening, accounting for its offset from the end effector. Batch related measurements when available. A surface point is not a grasp pose, a point inside the rim is not full-object clearance, and placement is not official task success. Compare requested motion with observed change; when progress stalls, identify the blocker before repeating it.

Occlusion, uncertain correspondence or changed geometry makes the relation unknown. Re-observe the missing fact; do not invent hidden boundaries or infer holding from gripper state alone.
```

这些经验给出判断方法、来源与失效条件，没有固定轨迹坐标、位移、方向、角度或力值。
其中 LIBERO 的 learned pick 前提不能推广为真机通用策略。旧经验中其他既有内容不在此清理范围。

## 验证计划与停止条件

1. **包与工具输入验证**：两个版本的语言材料完全相同；旧材料、源码与配置哈希不变；按 RPent 记忆加载路径验证索引与两篇经验可读。确认实际工具声明分别为 17/19 个。验证两个扩展工具的历史回放、缺失高分辨率数据、错误帧/像素与混合表面行为。使用已有研究工具测试和隔离 Docker 检查，报告实际命令与结果。
2. **相同条件的 10 轮筛选**：任务 0、3、4、6、8，各 seed 0，text/tools 各一次。Qwen3.8 Flash、300 秒、30 次模型请求上限、16384 token 配置均保持一致。300 秒沿用用户最近的 Qwen 预算要求。每对交替先运行哪一组；串行执行，减少共享推理负载差异。原版不新跑。
3. **判据**：官方成功率为主；记录零动作率、首次动作前全部工具调用、模型请求数、完整输入/输出 token（可获取时）、模型等待与总时间。逐例记录动作前最后一个未解决事实、错误目标分割、未到位后重复动作、工具参数错误。所有均值附分母，零动作轮单列。
4. **工具收益**：同时记录采样点数量、原生分割次数、工具执行耗时/调用次数，避免把隐藏计算挪进工具就算收益。text 与 tools 的差异只估计程序可用性的增量；不能从这两个组证明经验本身优于原版。历史结果只作背景。
5. **异常处理**：超过预算计有效失败；网络/服务等意外保留记录、修复后重跑同一单元。不得按“结果不好”选择性重跑。预算截断保留在成功率分母，不把截断耗时当完整任务耗时。若某组未使用工具，解释为工具未被采用，不能声称工具无效或有效。
6. **阶段终点**：完成 10 轮后报告全部结果及不确定性。每组仅 5 次，主要用于发现流程缺陷，不足以证明总体成功率提升。需要扩大样本、改经验或改工具时，提交具体后续修改供批准，不自动继续优化。

## 后续新工具方向（不在本轮实施范围）

`sensor_motion_evidence` 可把跨帧比较封装起来：输入两个明确的观测步骤、同相机/分辨率下同一可见物理特征的两次选点，以及可选的已请求末端目标；从对应 RGB-D/world 和 proprio 中计算物体点位移、末端位移、二者相对位移、目标残差及变化，附有效样本量和表面离散度。

输出只描述观测变化，不能宣称抓稳、碰撞、IK 失败或任务成功。选点同一性由调用者提供，工具不能自动证明；遮挡、外观歧义、缺帧或退化深度返回 unknown。它可能减少重复比较，但还需要验证这些失败轨迹中是否确实存在可对应的可见特征，才值得新增。

另一个独立接口修复是让 `segment` 附加准确的可读文件路径，保留原 `segment_artifact` 字段。当前已经复现目录名/文件路径歧义，但只涉及少数案例；其具体 diff 与回归测试须另行审核，不能当成本轮主要成功率优化。
