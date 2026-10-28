# Flexiv：GPT-as-Policy 直接 EEF 模式审核稿

状态：**本地替换稿已实现；远程独立审核目录验证；尚未替换运行中的真机服务。**

本稿将 GPT-as-Policy 的 GPT-only 工作流适配到现有 Flexiv 真机接口：模型根据图像、自身状态和本轮历史决定 EEF 目标，检查执行结果后继续。首轮建议沿用 `gpt-6-astra/high` 和现有 `move_tcp`，先验证提示与工具说明的影响；不将此轮称为原仓库控制算法的等价复现。

## 来源和修改范围

固定来源版本：`anonymous-report-421/GPT-as-Policy@8f3d362b077d8efb77e2a7274d5b2c20e2243846`。

- [GPT-only 工作流](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md)
- [EEF 与机器人约定](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md)
- [本轮状态与证据约定](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/teacher_context.md)
- [直接 EEF 执行](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo_server/gpt_only_client.py)
- [执行前拒绝与错误恢复](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/skill/run.py)

实际替换：

1. `robots/flexiv/prompt_bundle.py`：完整系统提示与任务模板，覆盖政策角色、观测、EEF、接触、恢复和结束判断。
2. `robots/flexiv/toolkit.py`：同步 `localize_target`、`move_tcp`、`align_tool_down`、`set_gripper` 的模型可见说明；函数签名、执行代码和数值检查不变。
3. RPent 公共文件工具与 `finish` 的真实声明随审核快照一起展示；不修改其他机器人的公共提示或工具。

入口核查：网页与 CLI 均由 `RobotSpec.prompts.render` 构建机器人系统/用户消息；工具装饰器的说明独立进入模型。Flexiv 常规任务没有额外的探索指南注入。Codex 的宿主指令和运行权限仍由 SDK 配置拥有，本提示不能扩大工具权限。当前 Flexiv 经验只读，历史经验不是本轮状态；本轮不训练或自动发布经验。

逐句审核请先看 [当前原文 → 候选原文的 A01–A22 对照](flexiv-gpt-policy-text-diff.md)，其中标明真实替换、保留、新增及配置项，并包含完整系统文本和工具说明差异。

## 逐项不适配与建议

下表全部是**建议稿**。审核时可按编号选择；已写入候选文本不表示已在真机启用。

| 编号 | 来源约定或当前冲突 | 非夕适配建议 | 本稿处理与审核关注 |
| --- | --- | --- | --- |
| A01 | RoboDojo 双 ARX X5、左右双臂目标 | 改为单 Flexiv Rizon4 和一个夹爪 | 已改，不使用 left/right 字段 |
| A02 | head/left-wrist/right-wrist 三路 RGB | 采用实际 side/wrist 两路 RGB-D；记录各自帧号和缺测 | 已改，不声称存在第三相机 |
| A03 | EEF 是 X5 link6，环境原点坐标 | 使用 Flexiv 原生工具 TCP、robot-base 米、wxyz | 已改；侧装 +Z 不代表桌面向上 |
| A04 | X5/Panda/DROID 各自几何偏置 | 仅使用当前观测内的工具补偿，旋转时一起变换 | 已改，不复制其他机器人的长度 |
| A05 | `gripper_closed` 布尔值/0–1 命令开度 | 使用 `set_gripper(width_m)`，0–0.098 m；实际开度和力反馈独立解释 | 已改；抓住与否仍需证据 |
| A06 | 本地 DLS IK，每次 ACK 后重新算关节 | 沿用 Flexiv 原生笛卡尔轨迹，由设备控制器处理运动 | 已改，模型不发关节命令；不宣称复用了 DLS IK |
| A07 | `steps=1..5`，25 Hz，短段后观察 | 首轮每次一个目标、实际到位后返回观测 | **重点审核**：这不是同样的时间片。若要固定时长控制，需要另实现保持和中断语义 |
| A08 | 每目标 ≤5 cm/0.35 rad | 首轮保留现有 ≤50 mm/10°、20 mm/s 等控制器限制 | 已按实际语义写；本稿不调整数值 |
| A09 | 原生 success/timeout/remaining_steps | 根据可观察证据结束，模型判断与物理核验分开 | 已改，无官方真机判分器 |
| A10 | 低预期成功率不能提前结束，持续到原生终止 | 单次感知失败先恢复；故障、授权失效、无反馈或预算结束可终止 | **重点审核**：不能把仿真持续执行规则照搬真机 |
| A11 | 参数拒绝明确 `no_execution/retryable` | 只读定位错误可换点/换视角；运动失败必须根据实际状态和执行证据区分 | 已改，不虚构当前接口有统一 no_execution 字段，不自动重放动作 |
| A12 | 某些任务必须释放并双臂回初始位 | 以实际任务要求为准；插入后是否释放不能由通用模板决定 | 已改，reset_home 仅在操作员明确要求回参考位时使用 |
| A13 | 仿真无真机桌面/工作区门槛 | 如实说明现有桌面及工作区检查，不能靠提示绕过 | **重点审核**：桌面附近旋转仍会受 50 mm 门槛约束；若受阻，另审控制规则 |
| A14 | 来源保留正常图像/计算/笔记能力 | 使用当前实际开放的分析工具；机器人仅走 RPent 声明接口 | 已改，不要求开放第二控制连接，也不将 shell 写成绕过工具的途径 |
| A15 | 来源固定文件目录、request_id、next_call | 使用当前 output_dir、保存 step 与动作后返回结果 | 已改，不要求提交不存在的字段或伪造目录 |
| A16 | 持续会话记忆，历史结果不能当当前状态 | 保留本轮进展笔记；既有 Flexiv 经验只作背景 | 已改，不复制来源的成功演示作为本轮成功证据 |
| A17 | 来源 GPT-6/xhigh | 首轮沿用已验证的 Astra high，避免同时改变推理档位 | **可选审核**：若改 xhigh，应单独记录；提示不能代替实际 SDK 配置 |
| A18 | 来源全部公开说明用英文 | 保留 API 标识与原任务；公开过程/结果用中文，便于现场审核 | 可改回英文；控制语义不受此选择影响 |
| A19 | 容器放置的具体经验，当前提示也强制朝下、接触后抬5 mm | 朝向和释放策略由任务阶段决定；朝下助手为可选工具 | 已删除通用强制放碗流程，不注入 U 盘动作脚本 |
| A20 | 本项目后续目标包含触觉，但当前真机 RPent 未传入 | 明确当前没有指尖触觉流或六轴插入力反馈 | 已改；夹爪力不等于插入力，接触闭环增益尚未验证 |
| A21 | 原仓库直接模式仅 EEF，无高层动作助手 | 首轮以 move_tcp + set_gripper 为主要动作，保留紧急停止和只读感知 | **可选审核**：现有 move_delta/align_tool_down/reset_home 仍会在工具目录中出现，本稿仅改变使用规则；若要求严格两种动作，应另做服务端工具白名单 |
| A22 | 当前 RPent 说明要求完整物体可见 | 定位可见、可辨识的完整表面特征；允许其他部位遮挡，不推测隐藏几何 | **重点审核**：这是感知工具的语义调整；像素/边界/有效深度检查仍由原实现执行 |

## 建议的首轮实验配置

- 模型：实际远程 Codex SDK `gpt-6-astra`，`high`；沿用当前任务预算。
- 输入：实际双相机 RGB-D、标定、自身状态和本轮历史；现有公开感知接口继续可选使用。
- 输出：由模型自主选择 `move_tcp` 的绝对 EEF 目标和单独夹爪命令；每动作后检查实际变化。
- 任务：沿用用户原文“将 U 盘插到蓝色槽中。”；不添加人为抓取位姿、插入轴或动作序列。
- 记录：提示全文、工具说明及参数、本轮图像、请求/响应和动作结果；模型 finish 与物理成功分别报告。
- 本轮回答：替换提示与工具说明后，模型是否能从只读感知错误恢复、形成合理动作并取得任务进展。
- 本轮不能回答：固定时间片控制是否更好、触觉是否提升、相对六维新接口是否提升。它们尚未在本稿实现。

## 审核与启用

建议首先确认 A07（到位后观察）、A10（真机终止规则）、A13（保留控制门槛）、A21（工具仍可见）和 A22（局部特征定位）。其他项目按表中建议适配。

审核通过后，再将候选文件同步到实际源码并只重启空闲 dashboard，让下一轮取得新提示与工具说明；无需重启采集器或改动控制器。启动前依照现有流程核实现场启用状态。审核期间不会提交任务或机械臂命令。

完整实际渲染的 system/user 提示、工具声明及验证结果位于本项目 `artifacts/flexiv-gpt-policy-review-20261027/`，其中任务和输出目录仅为预览变量，不是新实验记录。

## 已完成的静态与远程回归验证

- 远程独立源码目录执行 `python -m pytest tests/unit_tests/robots/flexiv -q`：62 passed，0.64 s。
- 两个候选 Python 文件 Ruff 检查、格式检查通过。
- 工具源码去掉说明字符串后，AST 与运行版本一致；13 个声明去掉说明文本后，参数结构与 readonly 标记一致。
- `motion.py`、`env_server.py`、`env_client.py`、`perception.py`、`robot_spec.py` 哈希与运行版本一致。
- 模型输入静态渲染通过，无未填模板变量；候选模块导入路径已确认来自独立审核目录。
- 运行中的 prompt/toolkit 文件哈希保持原值。没有调用机器人 handler，没有启动仿真或真机实验。
- 未运行完整仓库测试或完整模型推理；上述检查不代表新提示能提高真机成功率。

远程审核目录：`/home/zwy/work/embodied_harness/reviews/flexiv-gpt-policy-20261027/`。
