# Qwen v3 最小修订草案（待批准；未接入）

建议范围：修复已复现的批量采样参数契约；建立独立、精简的经验副本；替换一句过宽的任务前置要求。先做软件验证，只修复工具补跑受缺陷影响的 v2 任务 0；然后用两个独立环境跑 v3 任务 0/4/8 各 seed 0 一次。均为 Qwen Flash、远程直连、300 秒、30 请求、16384 token。总计最多 4 次有效尝试，不扩大至 50 次，不自动继续修改。原版和 v2 材料、已发布工具版本、原工作台选择、控制器均保留。

## 1. 修复明确的工具契约缺陷

拟修改 Git 文件：`examples/manual-workbench/sensor_patch_batch.py`、`examples/manual-workbench/candidate.json`；增加 `tests/unit_tests/robots/libero/research/test_high_resolution.py` 中的回归用例。发布新的不可变工具版本，仅选入本次候选工作台，原版本不覆盖、不删除。

当前声明：`radius` 是整数，范围 0–5、默认 2。实现对所有半径要求至少 3 个有效点，因此声明允许的 0 永远不能产出有效结果。

声明前后：

```diff
 "radius": {
   "type": "integer",
-  "minimum": 0,
+  "minimum": 1,
   "maximum": 5,
-  "default": 2
+  "default": 2,
+  "description": "Patch radius in pixels. For a single pixel, use back_project."
 }
```

实现前后：

```diff
 radius = params.get("radius", 2)
+if radius < 1:
+    return {"error": "radius must be at least 1; use back_project for a single pixel"}
 out = []
```

`candidate.json.source` 与源码同步生成；其余描述和计算不变。保留有效样本数、深度和混合表面检查，不把不可靠点伪装成有效结果。默认半径和所有既有有效输入结果应逐值一致。

依据：任务 0 四次 radius=0 调用共 20 点均失败；全有效合成平面同样复现，改为现有 radius=1 即有结果。这只能修复确定缺陷，不能单独解决任务 8 的零动作。

## 2. 独立的精简经验包

拟新增运行目录：`language-materials/qwen-evidence-v3/`。从 v2 复制 system/user/guide，系统提示词与指南字节不变。该副本的 memory 只放以下索引和三篇经验，不携带旧的 task-specific/task-family/global 轨迹库。原 v1/v2 完整目录和历史记录不删、不改。适用范围仅为这次 LIBERO 抓取搬运筛选，不能作为其他任务、真机或 UniVTAC 的默认经验库。

沿用已有 `memory/libero/next-action-evidence.md` 和 `memory/libero/object-relative-transfer.md` 原文；拟新增 Git 源 `memory/libero/grasp-feature-evidence.md`。在 Git 的 `memory/libero/MEMORY.md` 登记第三篇；为避免覆盖已发布 v2 的索引片段，独立候选索引源保存为 `validation/qwen-evidence-v3-screen3-20261107/memory-index.md`，内容如下：

```markdown
# LIBERO manipulation experience index

Read the entry matching the current unresolved decision. These are conditional hypotheses, not fixed trajectories or proof of success.

- [libero/next-action-evidence.md](libero/next-action-evidence.md): Before repeated localization, decide which evidence the next available primitive actually needs.
- [libero/grasp-feature-evidence.md](libero/grasp-feature-evidence.md): For a manual handle grasp, distinguish the handle from body, cavity and background; assess approach geometry and stalled motion.
- [libero/object-relative-transfer.md](libero/object-relative-transfer.md): When holding or placement is uncertain, check object-relative evidence and observed motion.
```

Git 源索引只追加下列一条（运行候选索引使用上面的完整三条版本）：

```diff
+- [grasp-feature-evidence.md](grasp-feature-evidence.md): Ground a manual handle grasp in feature identity, approach geometry and observed motion.
```

新经验完整草稿：

```markdown
# Ground a manual grasp in the visible feature

- id: grasp-feature-evidence
- scope: libero
- kind: perception
- title: Ground a manual grasp in the visible feature
- applies when: Considering a manual grasp of a visible narrow handle on a wider object.
- symptom: Repeated surface scans without a grasp, or open-finger descent that does not reach its target.
- evidence:
  - cells: 9cbe14f94f25bc734075; a4ad5d50d4b873066dd3
  - attempts: two failed episodes reviewed; not a successful intervention
- confidence: hypothesis; task benefit unvalidated
- related: next-action-evidence; object-relative-transfer

Label the intended grasp feature in the image before querying depth. Distinguish solid handle, handle opening, body and background; similar coordinates do not establish the same surface. If correspondence remains unclear, obtain a more informative view or a relevant segmentation rather than scanning unchanged pixels indefinitely.

A valid surface point alone does not specify a feasible end-effector pose. Manual grasping also needs evidence for approach clearance and finger orientation. Choose between a supported learned grasp and a manual approach using the current target and observed failure, not an unconditional ban inferred from an old episode.

Compare requested motion with the returned pose. A stalled open-gripper descent is not a completed grasp or evidence that an object is seated. Resolve the blocked approach before repeating it. When the feature is occluded or clearance is unknown, preserve that uncertainty instead of inventing a grasp pose.
```

这篇是有明确条件的任务族判断方法，不是通用的强制抓把手策略；没有坐标、固定方向、位移、角度、力值或轨迹指令。

依据：三轮都收到完整新索引条目，却选择旧经验；原索引有 213 个链接、32627 字符。任务 8 读取了带“禁止 learned pick”及固定轨迹的历史文字，随后在同一帧做了 176 点扫描。该时间顺序支持经验干扰假设，但尚不能证明移除旧材料就提高成功率。因此只做隔离候选，不清理原库，也不把经验正文加到系统提示词。

## 3. 替换一句过宽的前置要求，不追加长提示词

仅候选 `language-materials/qwen-evidence-v3/user.md` 中替换以下片段；对应变更另存本次验证目录的 `user.patch`。原版与 v2 用户提示词不改，v1 的简短三条附加提示保留。

```diff
-Read the language guide and the relevant experience, identify and localize the
-target and destination in this scene, then perform the task. Select the available
-interfaces from their declarations; no historical interface is prescribed.
+Read the guide and index, then choose the next available primitive. Read experience
+for its unresolved blocker. Resolve only the evidence that primitive needs;
+defer later placement geometry. Follow the declared interface contracts.
```

依据：原句把“目标和目的地都定位好”放在行动之前。任务 0 在抓取前进入篮口测量循环；现有 pi0_pick 的必填参数只是目标描述。新句仍要求身份和必要的可行性证据，不能解释为无条件强迫动作。

## 验证与结果口径

1. 远程验证半径 0 的清晰拒绝、半径 1–5/边缘像素、无效深度/缺帧；复算历史 247 个有效样本，确保合法输入输出不变。确认 schema/source 一致、发布新版本可在 Docker 执行，旧版本哈希不变。
2. 验证候选经验恰为三篇，索引链接全部可读、无旧任务轨迹，原材料/核心代码/原工作台不变。渲染检查确认系统提示词不含经验正文，user 只发生上面的替换；不能把“可读”写成“模型已读取”。
3. 统计器单独记录顶层执行错误、patch 逐点失败、容器质量拒绝；不能再用顶层错误为零概括全部感知结果。为统计补充一个包含逐点错误的实际回放用例。
4. 完成软件检查后，先保持 v2 语言材料、预算和其他工具不变，仅选择修复后的采样工具，补跑任务 0/seed 0，作为缺陷修复后的独立记录，不覆盖原尝试。如果出现新基础设施或实现缺陷，停下处理，不进入 v3。随后 v3 任务 0/4/8、seed 0 各一次，两个独立环境并行。官方成功率为主，记录经验实际读取、首次动作前全部调用、抓取尝试、有效/失败采样点、模型等待和 token。300 秒正常超时仍算失败；基础设施或已确认实验实现缺陷保留独立记录，处理后重试同一单元，不掩盖事故。
5. 本轮 v2 任务 0 受工具契约缺陷影响，应标注为受缺陷影响的尝试；修复前不能拿它作干净的有效性对照。任务 4/8 未触发该缺陷。现有记录和原始汇总保留，另附更正。
6. 一次补跑及三次候选筛选后停止并报告。与上一批的比较仅为开发筛选，因为同时改变工具契约与经验选择；不足以区分各改动的因果贡献，也不能证明相对纯文字经验的程序收益。不再重跑最初原版，不自动扩大实验。
