# GPT-as-Policy 原文 → 非夕真机适配建议

状态：**仅供逐条审核；本轮只改审核文档，不改提示代码、不部署服务、不启动真机。**

本稿以 GPT-as-Policy 的 GPT-only 原文件为唯一对照基线。每项包含原仓库英文摘录（附固定版本与行号）、建议保留/替换的文字、原因和待你决定的部分。之前以“现有 RPent → 候选稿”做的对照不对应你的需求，已标为历史参考。

## 目前到底修改到哪一步

| 对象 | 状态 |
| --- | --- |
| 真机运行服务 | 尚未切换到新提示；本轮不部署。 |
| 代码仓库 | `921bc5b` 已写入一份待审候选稿，该稿还未得到你逐条确认；它不是本稿建议自动生效的版本。 |
| 本文 | 基于来源重新给建议。尤其 A07、A17、A18、A21 仍须你选择，确认后才统一修改候选代码。 |

## 固定来源

仓库版本：`anonymous-report-421/GPT-as-Policy@8f3d362b077d8efb77e2a7274d5b2c20e2243846`。以下英文摘录只合并源文件换行，其余内容核对原文件；未将中文释义冒充英文原文。

- [hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md)
- [hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md)
- [hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md)

来源代码与文档采用 MIT 许可；版权和许可说明保存在 [来源 MIT LICENSE](gpt-as-policy-MIT-LICENSE.txt)。

## 原仓库没有、需要另行审核的项目

**A13（现场桌面/工作区门槛）、A20（当前触觉/力观测说明）、A22（局部特征定位）没有可对应的原文条款。** 它们属于现场补充或我提出的额外优化，不能称为原文移植。A19 中“所有任务朝下、接触后抬5 mm”同样不是来源要求。

## 逐项原文与适配建议

<a id="a01"></a>

### A01：自主策略角色：保留原意

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:8](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L8)

```text
Operate as the autonomous GPT policy
```

**适配到非夕的建议文字 / 选项**

```text
Operate as the autonomous policy for one physical Flexiv episode. Choose EEF actions from the original task, current observations and this episode’s history. No pi05 model is available; the implementation assistant does not choose online actions.
```

**为什么需要改：** 这是来源方法的核心，应保留。仅把运行场景补为单次非夕真机任务，不改成“先完成全部几何定位才行动”的规划器。

**请审核：** 建议采纳；属于方法原意的保留。

---

<a id="a02"></a>

### A02：机器人与相机名称：双 X5 改为单非夕

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:7](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L7)

```text
Robot: dual ARX X5, not Panda/DROID.
```

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:7](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L7)

```text
Views are `cam_high`, `cam_left_wrist`,
  `cam_right_wrist`
```

**适配到非夕的建议文字 / 选项**

```text
Robot: one Flexiv Rizon4 arm with one gripper. Views are side and wrist RGB-D. Inspect the available views and use their actual image dimensions and recorded frame identifiers.
```

**为什么需要改：** 来源的双臂和三路相机名称在你的现场不存在，应换成单臂、侧面及腕部。不能保留虚构的左右手或头部相机。

**请审核：** 必要适配；仅改现场事实。

---

<a id="a03"></a>

### A03：EEF 参考点与坐标：link6/环境系改为原生 TCP/基座系

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:13](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L13)

```text
`current_eef.left/right` refer to each arm's **link6 in environment-origin
  coordinates**, meters, quaternion **wxyz**.
```

**适配到非夕的建议文字 / 选项**

```text
tcp_pose and commanded EEF targets refer to the configured native tool TCP in robot-base coordinates, in metres and unit quaternion wxyz. This side-mounted arm’s base +Z is not necessarily table-up.
```

**为什么需要改：** 这是最关键的数值语义适配。命令仍是绝对 EEF 位姿，但参考点必须使用当前非夕工具 TCP；上移方向需要按桌面变换解释。

**请审核：** 必要适配；不能直接沿用 X5 坐标。

---

<a id="a04"></a>

### A04：末端几何偏置：替换机器人专属偏置说明

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:27](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L27)

```text
Do not reuse DROID's +0.1311 m pad offset.
```

**适配到非夕的建议文字 / 选项**

```text
Use only the recorded Flexiv tcp_to_grasp_translation_m. The grasp reference is TCP_position + R(TCP_orientation) × offset. Do not reuse another embodiment’s pad offset or add the flange-to-TCP length again.
```

**为什么需要改：** 保留来源“不照搬其他机器人偏置”的原则，换为你当前工具的补偿定义；不在提示里凭空固定一个新的末端长度。

**请审核：** 必要适配；以实际工具配置为准。

---

<a id="a05"></a>

### A05：夹爪参数：布尔开合改为现有米制开度

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:18](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L18)

```text
`gripper_closed`. True maps to opening=0.
```

**适配到非夕的建议文字 / 选项**

```text
Command the gripper separately with set_gripper(width_m), where 0 is closed and 0.098 m is fully open. Returned width and gripper force are measured feedback; a command or contact flag does not establish a secure grasp.
```

**为什么需要改：** 现有接口没有 gripper_closed 字段。建议先复用真实开度接口；若想连目标结构也严格一致，需要实现并验证布尔开合适配器，而不是只换文字。

**请审核：** 待你选择：复用米制接口，或实现来源形式的统一 action adapter。

---

<a id="a06"></a>

### A06：IK 与执行后端：来源 DLS 不能写成非夕已具备

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:21](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L21)

```text
Local damped least-squares IK is recomputed
  after every real ACK
```

**适配到非夕的建议文字 / 选项**

```text
The Flexiv adapter executes Cartesian EEF targets through the existing native controller. Use measured pose feedback after execution; do not issue joint targets or assume an IK target proves arrival.
```

**为什么需要改：** 来源是本地 IK 转关节目标；目前非夕后端走原生笛卡尔控制。可以保持 VLM→EEF 的接口思路，但不能在提示里宣称已经移植了来源 DLS IK。

**请审核：** 必要适配；底层算法是否另行移植要单独决定。

---

<a id="a07"></a>

### A07：短段控制：这是实现差异，不只是提示词改名

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:21](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L21)

```text
EEF mode executes 1–5 control steps.
```

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:30](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L30)

```text
Native controls are 25 Hz (0.04 s).
```

**适配到非夕的建议文字 / 选项**

```text
方案一（先复用当前控制器）：
Execute one bounded Cartesian target, wait for measured completion, then return observations for the next decision. Do not interpret this call as a fixed 25 Hz control segment.

方案二（更接近来源，需先实现）：
Execute the requested EEF target for a bounded short control segment, then hold safely and return fresh observations and measured tracking error before the next decision.
```

**为什么需要改：** 来源的固定短段是控制循环的一部分。方案一能先试“模型选 EEF”，但不等价于来源执行节奏；方案二需要真实的短段结束/保持/中断接口，现有 stop 会撤销启用，不能拿它冒充普通段结束。方案二实现前不能把那段话作为现有能力传给模型。

**请审核：** 重点待审：选择先复用现有轨迹，还是先做真正短段 EEF 后端。

---

<a id="a08"></a>

### A08：位姿范围：来源上限与真机现有上限不一致

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:19](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L19)

```text
Per-arm targets
  remain within 0.05 m and 0.35 rad of the current measured pose.
```

**适配到非夕的建议文字 / 选项**

```text
Each target must remain within the limits actually reported and enforced by the Flexiv server. The current move_tcp limit is 50 mm translation and 10 degrees rotation from the latest measured TCP pose.
```

**为什么需要改：** 距离仍可保持 5 cm；姿态目前是 10°，与来源 0.35 rad 不一致。建议首轮如实写当前限制；若要改成来源数值，必须修改并验证执行层，不能靠提示放开。

**请审核：** 待你审核限制；本轮没有修改控制数值。

---

<a id="a09"></a>

### A09：原生成功与预算信号：改为真机证据判断

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:19](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L19)

```text
RoboDojo reports native success separately
from a partial-credit score
```

**适配到非夕的建议文字 / 选项**

```text
This physical setup has no native task-success score. Track the configured experiment budget and report observable task evidence separately from the model’s completion judgment and the planner’s exit status.
```

**为什么需要改：** 不能要求真机等待一个不存在的 success、分数或 rollout_finished 信号。建议保留来源“外观完成、动作执行、真实任务成功必须区分”的原则。

**请审核：** 必要适配；没有人为添加一个官方判分器。

---

<a id="a10"></a>

### A10：不能因低成功预期就放弃：保留继续恢复，补真机结束条件

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:67](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L67)

```text
Low expected success
is not permission to stop early.
```

**适配到非夕的建议文字 / 选项**

```text
Do not abandon the task solely because one perception or alignment attempt fails. Continue supported observation and recovery within the budget. End on supported completion, exhausted recovery, operator stop or a hardware/feedback fault.
```

**为什么需要改：** 来源鼓励继续执行，不是要求无论真机反馈如何都用完预算。建议保留失败后重新观察与调整的原则，同时写清真机硬件故障和现场停止的出口。

**请审核：** 重点待审：恢复强度与结束条件，而不是默认第一次感知失败就 stuck。

---

<a id="a11"></a>

### A11：执行前拒绝：保留可修正原则，但不能伪造未执行证据

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:68](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L68)

```text
Validation rejections execute nothing and can
be corrected; transport/physics errors are fatal to this attempt
```

**适配到非夕的建议文字 / 选项**

```text
Read-only perception failures can be corrected without replaying an arm action. Retry a rejected motion only when the response establishes that no motion executed. If execution or acknowledgement is uncertain, stop for recovery instead of replaying the command.
```

**为什么需要改：** 来源提供执行前拒绝的明确协议；当前 RPent 不是每个错误都含 no_execution。只读查询可以修正；运动指令的执行状态不明时不能按“无动作”处理。

**请审核：** 必要协议适配；统一错误字段可作为后续实现，而不是当前已完成能力。

---

<a id="a12"></a>

### A12：任务结束是否回位：移除仿真专属双臂返回要求

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:25](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L25)

```text
`requires_arm_return=true`, completion also requires both arms near their
episode-start end-effector positions and orientations.
```

**适配到非夕的建议文字 / 选项**

```text
Completion conditions follow the actual physical task. Release or return to a reference pose only when required by the task or explicitly requested by the operator; do not add simulator-specific arm-return conditions.
```

**为什么需要改：** 来源的回双臂初态是部分 benchmark 的判分要求，不应套到插 U 盘。复位还是一个真实动作，需要实际任务或现场明确要求。

**请审核：** 必要适配；不能默认每个任务最后回参考位。

---

<a id="a13"></a>

### A13：桌面/工作区条件：原仓库没有这套现场门槛

**GPT-as-Policy 英文原文**

**无对应原文。此项是现场补充或额外优化，不是原文替换。**

**适配到非夕的建议文字 / 选项**

```text
Respect the workspace and motion limits enforced by the physical robot service. Revise rejected targets within those limits; do not bypass a guard through another control connection.
```

**为什么需要改：** 这是非夕现场执行约束的补充，不是 GPT-as-Policy 原文条款的替换。具体 4 mm、50 mm 等门槛来自现有控制代码；其合理性需要独立审核，不能把它说成来源方法的要求。

**请审核：** 额外现场适配，需你审核；数值规则与提示规则分开决定。

---

<a id="a14"></a>

### A14：图像、计算、笔记能力：建议保留来源的完整分析工作流

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:8](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L8)

```text
normal file/image
inspection, code execution, calculation, planning and notes.
```

**适配到非夕的建议文字 / 选项**

```text
Keep the available image inspection, calculation, file analysis and episode notes. Use the recorded robot-action service for physical control; analysis tools must not open a second controller connection or modify the execution evidence.
```

**为什么需要改：** 来源不是只能输出一个 JSON 的 VLM，它保留了看原图、计算和本轮笔记。迁移时应核实这些能力确实开放；受限目录与记录只读可保留，不应暗中删掉能力却称完整复现。

**请审核：** 建议保留来源能力；实际开放范围要在 SDK/工具配置里核实。

---

<a id="a15"></a>

### A15：协议与路径：换成 RPent 真实字段，或另做兼容服务

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:14](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L14)

```text
`workspace.json` supplies exact
paths and the Python interpreter.
```

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:39](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L39)

```text
matching
   `request_id`
```

**适配到非夕的建议文字 / 选项**

```text
Use the current RPent observation step and output directory. Bind each decision to the latest saved observation and preserve its execution result. Do not invent request_id, next_call or workspace fields that this adapter does not return.
```

**为什么需要改：** 建议先采用当前真实 step/output_dir。若要完全保留来源 start/act/request_id 交互，应实现协议适配层；这也是程序工作，不是同义替换一句提示。

**请审核：** 待审：先保留现有 RPent 协议，还是实现来源风格的 start/act 包装。

---

<a id="a16"></a>

### A16：历史经验：保留原文原则

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md:15](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md#L15)

```text
Prior successes are not evidence that the current episode is complete.
```

**适配到非夕的建议文字 / 选项**

```text
Prior successes do not establish the current episode’s state or completion. Maintain notes on observed progress, tracking errors and corrections from this episode.
```

**为什么需要改：** 这条本来就来自来源，可以基本保留。只需把笔记目录映射到实际运行目录，不需要写入任务专属的旧成功脚本。

**请审核：** 建议保留；并非额外增加“先调用经验才能动作”的要求。

---

<a id="a17"></a>

### A17：推理档位：来源 xhigh 与当前 high 由你决定

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md:4](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md#L4)

```text
a persistent GPT-6/xhigh agent
```

**适配到非夕的建议文字 / 选项**

```text
这项应修改实际 SDK 设置，不用提示词假设生效：
选项一：保持当前 gpt-6-astra / high。
选项二：若后端支持，配置 gpt-6-astra / xhigh 并核实实际生效。
```

**为什么需要改：** 你要求参照来源，因此必须明示来源是 xhigh，不能把我之前“首轮先 high”的建议当成你的已确认选择。此项没有真实的提示词替换句子。

**请审核：** 配置项待你选择；本轮没有修改档位。

---

<a id="a18"></a>

### A18：公开语言：保留英文，还是改为中文

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:64](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L64)

```text
Use English for every public decision explanation, progress update, working note
and final report
```

**适配到非夕的建议文字 / 选项**

```text
默认更接近来源：保留上述英文输出要求。
如果你希望中文：
Use Chinese for public decision summaries and reports. Preserve protocol field names, enum values, file paths and the original task instruction.
```

**为什么需要改：** 中文是我为了现场阅读提出的可选修改，不是非夕硬件必需。建议由你选择；不能默认为“按原文移植”时已经改成中文。

**请审核：** 可选修改；不影响动作参数语义。

---

<a id="a19"></a>

### A19：容器放置经验：保留适用范围，不扩大到插入任务

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md:31](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L31)

```text
For container placement, clear the rim with both the object and fingers before
moving laterally
```

**适配到非夕的建议文字 / 选项**

```text
Keep container-clearance guidance conditional on a container-placement task. Choose grasp and insertion orientation from the instructed task and current observations; do not apply container-release steps to every manipulation task.
```

**为什么需要改：** 来源这段本来有“For container placement”的前提，并没有要求所有任务都朝下或接触后提起 5 mm。此前那些强制规则来自我们的 RPent 真机提示，不应归因给来源。迁移时可以保留原文的条件性。

**请审核：** 建议保留条件性；不新增 U 盘专属动作脚本。

---

<a id="a20"></a>

### A20：触觉与六轴力：属于额外传感说明

**GPT-as-Policy 英文原文**

**无对应原文。此项是现场补充或额外优化，不是原文替换。**

**适配到非夕的建议文字 / 选项**

```text
Use only sensor channels actually supplied by the adapter. The current RPent Flexiv observations do not contain fingertip tactile streams or six-axis insertion-force feedback; gripper force is not insertion force.
```

**为什么需要改：** 此次选用的 GPT-only 原始契约主要使用 RGB 和自身状态，没有一条触觉工具的通用要求。这段是针对你的现场传感接入情况补充的说明，不是来源原文的改写，也不意味着触觉接入已完成。

**请审核：** 额外现场事实说明；若之后接入触觉，需要按实际输出更新。

---

<a id="a21"></a>

### A21：动作工具范围：如果要忠实直接模式，建议真的约束动作集合

**GPT-as-Policy 英文原文**

[hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md:25](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md#L25)

```text
Only EEF actions are available.
```

**适配到非夕的建议文字 / 选项**

```text
For this direct-policy experiment, arm motion uses the EEF action interface and gripper commands; read-only observation/analysis and emergency stop remain available. No learned-policy or high-level task-action tools are used.
```

**为什么需要改：** 建议实验接口在服务端实际限制动作集合，而不仅靠提示要求模型不用 helper。现有 move_delta 仍属于 EEF 增量；align_tool_down/reset_home 等是否保留为动作应由你审核。此前候选稿保留全部工具可见，只是一个备选适配，不是原文严格模式。

**请审核：** 重点待审：严格 EEF 动作集合，或保留辅助动作。未实施新白名单。

---

<a id="a22"></a>

### A22：完整物体框/局部特征：原仓库没有这个要求

**GPT-as-Policy 英文原文**

**无对应原文。此项是现场补充或额外优化，不是原文替换。**

**适配到非夕的建议文字 / 选项**

```text
If a depth-localization helper is exposed, it is optional evidence for the policy, not a mandatory prerequisite for every EEF action. It may measure an identified visible surface feature without inventing occluded geometry.
```

**为什么需要改：** 来源没有 RPent 的 localize_target，更没有“必须整物体可见才能定位”的句子。把完整物体要求改成局部特征，是我针对当前 RPent 失败提出的额外优化，应该让你单独审核；不能包装成 GPT-as-Policy 迁移必需项。

**请审核：** 额外可选优化；未被你审核确认。

---

## 本稿校验与实施边界

- 22 项编号齐全；22 处来源摘录已核对固定 commit 文件，行号与链接一起保存。
- 本稿没有把不存在的短段控制、错误字段、传感流或工具白名单写成已实现能力。
- 本轮只生成审核文本；没有修改候选系统提示、工具代码或实际 SDK 配置。
- 审核后先确定动作后端（A07）及动作集合（A21），再让提示与真实接口一起保持一致。
- 通过代码检查只证明文档/接口一致，不证明机器人任务成功。
