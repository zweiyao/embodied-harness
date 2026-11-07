# 原版 LIBERO 空经验库对比实验（已批准，2026-11-07 启动）

## 目标和范围

在原有 LIBERO 工作台中比较 Qwen3.8 Flash 与 GPT-6 Astra 首次动作前的观测和工具调用次数。libero_10_task 的任务 0–9，每任务 seed 0，每模型一次，共 20 个有效实验；不重跑有经验库的对照，不使用 qwen-minimal-v1 新提示词。

这里的“原版”具体指此前 50 轮使用的 language-materials/v1（language-c592f23a3a324c08）。只移除经验库条目，保留其原操作指南；不是完全移除人工操作建议的实验。

## 具体配置和材料变化

仅新增独立目录 /home/zwy/work/embodied_harness/language-materials/v1-empty-memory，不覆盖 v1：

- system.md、user.md、guide.md：与 v1 原文件逐字节相同。
- memory/MEMORY.md：从原经验链接索引变为以下完整内容：

```markdown
# Experience index

No experience entries are available in this experiment.
```

- memory/global、memory/task-family、memory/task-specific：新材料包不包含任何经验文件。
- manifest.json：只登记上述四个文件的 SHA-256，使用独立版本号。

外部批处理通过工作台现有 language_materials 字段选择此包。旧提示词要求读取 guide.md 和 MEMORY.md 的行为保留，因此这两次读取仍计入文件调用；它们不计入观测调用。原版文件、核心代码、工具说明和控制参数均不修改。

两个模型统一使用当前 17 个 native 工具、max_turns=30、max_tokens=16384、planner_timeout_s=1500。Qwen 使用现有 qwen3.8-flash / API / reasoning_effort=none；Astra 使用现有 gpt-6-astra / Codex / reasoning_effort=low。不同适配器的 max_turns 不保证代表同一内部请求单位，主指标使用双方都有的 tool_request 事件。

并行方案（根据用户追加要求，已批准执行）：建立两个临时独立工作台进程，均绑定回环地址空闲端口；一个使用 Qwen Flash，另一个使用 Astra，各自顺序执行任务 0–9 / seed 0。每个工作台有独立会话、环境进程、LIBERO_CONFIG_PATH、输出目录与冻结材料；原 8092 工作台保持原配置。两个工作台共享现有 VLA 49337 与 SAM 37867 推理服务，沿用现有服务锁，不改服务实现。共享推理会排队，因此不能把并行耗时与旧串行耗时直接当作模型速度差异。每轮新会话，不把前轮结果写入后轮经验。

## 统计口径

- 主指标：首次动作工具调用之前的 view_env_state 与 read_image 调用次数，逐任务列出并分别计算模型均值、中位数、范围。
- 单列 segment、back_project、view_camera_meta；单列文件读取与目录查询；同时报告首次动作前的全部工具调用数。
- 按 tool_request 计调用尝试，另外列失败调用。首次动作工具为 move_to、move_pose、pi0_pick、pi0_doubled、release、set_gripper、rotate_pitch、rotate_wrist。首次动作若因参数等错误未执行，另行标记，避免当作已开始物理执行。
- 不把同一工具返回的多张图计成多次调用；动作返回附带的图像不计为主动观测调用。
- 未发生动作的轮次单列，报告终止前调用数及原因；不填 0 混入“首次动作前”的均值，明确每个均值的分母。
- 记录到首次动作的时间、完整轮次耗时和官方成功结果。每任务只有一次，仅为探索性平均，不声称可靠的成功率提升或经验因果效应。

## 启动前和结束后验证

1. 核实工作台 ready，保留原配置、模型与网络设置，检查本地/远程独立修改。
2. 在远程验证材料冻结和模板加载，原三份文本哈希不变，冻结目录只有空索引而没有经验条目，原保护文件哈希不变。
3. 核查两个模型连接。Qwen 如需沿用此前域名级直连，明确记录并在结束后恢复原代理；不改变 Astra 路由。
4. 审计每轮文件读取记录：不能成功读取任何原经验库或历史实验经验；发现串读则该轮作为实验配置意外排除，先修复后重跑同一任务/seed，不能带污染结果继续统计。现有文件读取工具并非整个文件系统的沙箱，不能仅凭目录为空宣称全局禁止访问。
5. 超过 1500 秒算有效失败；请求/服务等意外单独保存，处理后重跑；正常任务失败不重试。
6. 用历史日志核验统计器对两种适配器的 tool_request 口径，并覆盖未动作、工具失败和一轮多工具情况。
7. 完成后恢复工作台及网络设置，更新看板的实际结果，提交推送小型摘要并更新 PR，不提交原始观测、录像或凭据。

用户已于本轮回复“开始实验”。两路独立工作台已启动，不切换原工作台配置；实际结果以独立运行记录为准。
