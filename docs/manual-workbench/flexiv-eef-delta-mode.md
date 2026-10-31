# RPent 非夕 EEF 增量模式

新增 `--control-mode eef_delta`：保留 RPent 的 planner、工具执行、记忆和逐步记录，让 VLM 根据图像和实际位姿选择下一次末端增量。默认 `native` 模式保持原来的 Flexiv 系统提示词。

2026-10-30 已部署至真机 RPent。首轮 Astra high 任务已结束，已实际验证短段执行与段末保持，但未完成抓取与插入；完整结果见文末记录。

## 提示词放在哪里

依照 RPent 的机器人扩展方式，`robots/flexiv/robot_spec.py` 注册同一个 `PromptBundle`；`prompt_vars["control_mode"]` 选择机器人自己的提示内容：

- `native`：`robots/flexiv/prompt_bundle.py` 中保留迁移前 `db7af7d` 的系统和用户提示原文。
- `eef_delta`：`robots/flexiv/prompts/eef.py`，仅包含角色、机器人、坐标、动作、反馈流程和完成判断。

API 与 Codex 使用同一份提示和工具声明，没有修改共享 `rpent/prompt/`、planner、会话或 dashboard 渲染代码。RPent 没有自动附加的通用机器人系统提示词；其约定就是由机器人目录提供 `PromptBundle`。

新模式采用逐步观察与执行，不要求每次动作先调用深度定位，也不要求所有任务先朝下、接触后一律抬升或放进容器。定位工具仍可作为辅助。控制程序原有的工作区、桌面、速度、授权与故障保护继续执行。

## 动作含义

```python
move_eef_delta(
    translation_m=[0.005, 0.0, 0.0],
    rotation_vector_rad=[0.0, 0.0, 0.0],
    steps=5,
)
```

这表示以执行时的实测 TCP 为起点，目标沿**机器人基座 +X** 增加 5 mm，姿态不变；朝这个固定目标执行五个 40 ms 控制步。不是每步增加 5 mm，也不保证整段实际移动 5 mm。返回实际位姿、目标误差和图像；模型根据实际进展决定下一步。

| 字段 | 含义 |
| --- | --- |
| `observe().state.tcp_pose` | 当前原生 TCP；基座坐标 `[x,y,z,qw,qx,qy,qz]`，米、wxyz 四元数 |
| `translation_m` | 基座轴平移增量 `[dx,dy,dz]`，米；范数最多 0.05 m |
| `rotation_vector_rad` | 基座轴右手旋转向量，弧度；范数为转角，最多 10°；不是欧拉角，零向量保持姿态 |
| `steps` | 严格整数 1–5；25 Hz，朝同一个已解析目标执行 |
| `set_gripper(width_m)` | 独立设置夹爪目标开度，0–0.098 m；臂运动保持原夹爪状态 |

目标计算为 `p_target = p_measured + translation_m`、`R_target = Exp(rotation_vector_rad) * R_measured`。左乘表示绕基座轴旋转；侧装非夕的基座 +Z 不等于桌面向上。相机坐标、桌面法向和抓取参考偏移使用观测中记录的标定。

段结束后，控制器保持实测位姿，再返回观测。因此整次工具耗时包含保持和采图，超过 `steps × 0.04 s`。模型调用期间不会继续追赶旧目标。两次调用之间以重新读取的实际位姿为基准，不累加上次尚未到达的目标。

## 从 GPT-as-Policy 借鉴什么

借鉴的是“图像与本体状态 → VLM 给出短程 EEF 目标 → 执行 → 再观察”的闭环，以及明确坐标、单位、姿态约定和以实际反馈判断进展。

[来源 EEF 契约](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md)实际使用绝对目标、X5 双臂和局部 IK。这里的增量参数是本项目适配，底层复用非夕原生笛卡尔控制；没有移植 X5 几何、关节控制或仿真暂停机制。

## 启用方式与工具清单

在现有 RPent CLI 或 dashboard 启动参数中添加 `--control-mode eef_delta`。配置和任务记录会保存 `control_mode`。本次没有新增网页逐轮模式选择器；当前模式由 dashboard 启动配置确定。

前提是外部 Flexiv env 已按 [短段部署说明](flexiv-eef-short-control.md)启用 `--supervised-control --eef-chunk-control` 并接入采集器短段路由；`reset_before_task` 必须为 false，避免隐式复位。程序在构建工具清单前检查这些条件，缺少能力会明确拒绝启动。

EEF 模式的动作工具为 `move_eef_delta`、`set_gripper`、`stop_motion`；保留观察、已配置的定位和 RPent 通用工具。原 `move_tcp`、`move_delta`、`align_tool_down`、`reset_home` 不在该模式的模型清单里。原生模式清单维持原有行为。没有新增控制器连接，也不自动启用机械臂。

## 验证与部署

2026-10-28，在远程实际 RPent 虚拟环境的隔离目录执行 **180 项检查通过**（0.77 s），包含新增增量动作、模式/工具/RPC契约及原有运动与采集器短段回归；Ruff 检查和格式检查通过。替身检查不调用真实硬件。

- 原生模式系统和用户提示的渲染结果，与迁移前 `db7af7d` 逐字一致。
- 新 EEF 系统提示按空白分词约 313 词，上一候选版约 985 词，缩短约 68%。
- 实际 CLI 帮助确认 `--control-mode {native,eef_delta}` 已注册。
- 运行中的 RPent 和采集器源码哈希保持不变；没有重启服务、调用模型或机械臂。
- 隔离候选目录：`/home/zwy/work/embodied_harness/reviews/flexiv-eef-delta-20261028/`，包含完整提示预览 `eef-prompt.md` 和验证摘要 `validation.json`。

2026-10-28 的上述检查仅为软件验证；后续真机记录见下节。


## 2026-10-30 真机部署与首轮

运行版本为 `00f33bb`，部署前针对当前采集器副本执行 180 项替身与回归检查通过。采集器新增 EEF 路由与四处集成钩子，环境开启 `--eef-chunk-control`，原 RPent dashboard 使用 `--control-mode eef_delta`。Astra high，25 次决策、1800 秒上限；无自动复位。原设置与代码备份于远程 `embodied_harness/backups/flexiv-eef-live-20261030T012314Z`。

操作员现场确认并启用后，RPent 自主执行“将 U 盘插到蓝色槽中。”；当前对话仅提交任务与读取记录，没有向运行模型追加策略或直接发送动作。

记录目录：`harnessvla/logs/20261030-09:24:38_dashboard_session/tasks/0001_flexiv`。

本轮耗时 299.1 秒，25 次决策、30 次工具调用。17 次 `move_eef_delta` 中 16 次成功返回保持状态，另有一次夹爪开度设置和一次显式停止。

| 实测项目 | 结果 |
| --- | --- |
| 成功短段执行时间均值 | 0.20055 s（每段 5 tick） |
| 成功短段保持时间均值 | 0.708 s |
| 成功短段实测位移均值 | 0.749 mm，范围 0.451–1.024 mm |
| 前 16 段累计净位移 | 9.583 mm |
| 成功短段最大 tick 延迟 | 1.282 ms |
| 夹爪设置 | 25 mm，`contact_detected=false` |
| 抓取／插入 | 均未完成 |

第 17 个短段完成了 5 tick，随后未能在 3 秒内满足保持停稳条件，采集器触发停止并对外返回 HTTP 500。真实底层异常为 `EEF segment stationary hold did not settle`，不是网络断开。Astra 随后调用 `stop_motion`，保存失败审计并结束。最终实读为 `Mode.IDLE`、`armed=false`、无 fault、无活动租约。保存的 step22 双视角 RGB 显示 U 盘仍在红色支座上，蓝色槽为空；与模型自报失败和夹爪无接触反馈一致。

当前瓶颈首先是动作的有效推进量：每次 0.20 秒运动后重新保持，在现有原生轨迹参数下每次只移动不到约 1 mm。最后一次停稳失败只确认复合判据未满足；当前日志未逐次记录保持期的全部判据，尚不能区分位置、姿态或关节速度的具体原因。以上不证明定位准确、接触控制可靠或方法收益，也没有据此放宽阈值。

小型汇总：[首轮结果 JSON](flexiv-eef-first-physical-20261030.json)。原始 SDK 事件、逐步 RGB-D、标定、控制 tick 与模型审计保留在远程实验目录，不加入 Git。
