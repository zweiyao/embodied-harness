# 非夕 EEF 短段适配：A03/A05 字段与 A06/A07 解释

状态：代码在远程隔离候选目录中验证，尚未替换运行服务，尚未驱动真机。其他提示条款继续待用户审核。

## A01 / A02

角色只保留：

```text
Operate as the autonomous policy for one physical Flexiv episode.
```

机器人与视角只保留：

```text
Robot: one Flexiv Rizon4 arm with one gripper. Views are side and wrist RGB-D.
```

## A03：实际如何读取和命令位姿

沿用来源 EEF 契约的列表形式，替换真实字段：

```text
- observe() returns state.tcp_pose: [x,y,z,qw,qx,qy,qz].
- The pose refers to the configured native tool TCP in robot-base coordinates.
- Position units are meters; quaternion order is wxyz.
- move_eef uses position_m, quaternion_wxyz and steps.
```

读取命令为 `observe()`，结果位姿在 `state.tcp_pose`；前三项是当前位置，后四项是当前姿态。`move_eef` 是本次新增的候选短段工具；旧 `move_tcp` 仍为到位后返回的接口。候选服务只有显式开启短段能力时才注册新工具；提示明确说明工具没暴露时不能调用。

## A05：夹爪字段

```text
- set_gripper contains width_m, measured in meters.
- 0 means closed; 0.098 means fully open.
- observe() returns state.gripper_width_m as measured opening.
```

夹爪仍单独调用真实 `set_gripper(width_m)`。没有将 X5 的 `gripper_closed` 布尔字段、0–1 开度或手爪几何原样传给非夕；短段手臂命令不会改变夹爪。这个分离接口是当前适配与来源统一目标结构的一项区别。

## A06：IK 是什么，为什么没有复制来源 IK

两套系统的上层都可以让 VLM 输出末端目标。区别在目标下面一层：

```text
GPT-as-Policy / X5:
VLM 的 EEF 目标 → 程序内 DLS IK → 关节目标 → 原生控制器

当前非夕适配:
VLM 的 EEF 目标 → 非夕 SendCartesianMotionForce → 非夕原生控制器 → 实际运动
```

IK（逆运动学）回答的是“末端要到这里，各关节应该转多少”。来源的程序自己算这一步；当前非夕接口已经接受笛卡尔末端目标，因此可以把转换与轨迹执行交给非夕的原生控制器。无需把 X5 的关节数、雅可比或 IK 数值参数移植到 Rizon4。

这不把 VLM 改成输出关节角，也不意味着复现了来源的 DLS 算法。新接口复用已装 RDK 1.9.0 的 `SendCartesianMotionForce`，保留现有速度和加速度上限。

## A07：短段与等待到位的区别

假设模型给出的目标在当前位置前方 2 cm：

| 方式 | 模型何时拿到下一次观测 | 到这时是否必须已经前移 2 cm |
| --- | --- | --- |
| 原 `move_tcp` | 目标到位并停稳后 | 是；否则超时/失败 |
| 新候选 `move_eef(..., steps=5)` | 执行 5 个 40 ms 控制步，结束旧目标并保持后 | 否；按实际到达位置和剩余误差继续决策 |

这里的 `steps=5` 是**朝同一个目标执行五步**，不是五个路径点，也不是每步都移动 2 cm。最多 1–5 步，对应 40–200 ms 的执行段。模型看到实际进展后，可以再沿原方向前进、调整姿态或改变策略。

真机不能像仿真一样在模型思考时冻结物理，因此新适配在段末做一次额外保持：

1. 读取段末实测 TCP。
2. 将这个位姿提交为保持目标，取消继续追赶旧目标的意图。
3. 核实保持已停稳，再按现有静止 RGB-D 流程采集。
4. 返回实际位姿、剩余误差、每步状态以及执行段/保持耗时。

所以**整次工具调用耗时会超过 40–200 ms**。这项保持行为与源仿真的时间暂停存在差别，已经明确记录，不声称完全相同。

## 实际接口

候选 RPent 工具 / RPC 字段：

```text
move_eef(position_m, quaternion_wxyz, steps)
set_gripper(width_m)
```

- `position_m`：绝对基座坐标 `[x,y,z]`，米。
- `quaternion_wxyz`：显式单位四元数 `[w,x,y,z]`；要保持姿态，就传最新实测姿态。
- `steps`：严格整数 1–5；布尔值、超范围值拒绝。
- 采集器路由 `/rpent/supervised/eef-chunk` 接收已有原生格式 `pose=[x,y,z,qw,qx,qy,qz]` 和 `steps`。
- 每 40 ms 向同一目标提交原生笛卡尔命令、读取新状态；记录真实 tick 时间和超时，不伪造严格实时频率。
- 故障、授权/租约失效、过期相机、不明 ACK、单步关节变化过大、节拍超时、保持失败等停止并撤销授权。
- 已明确未执行的参数拒绝返回 `no_execution=true, retryable=true`；正常段结束保留原授权期限，不自动延长或重新启用。

现有 50 mm / 10°、20 mm/s、桌面和工作区约束继续适用。新保持检查还有固定三秒截止时间和 5 mm / 1° 漂移失败边界，均需实际现场验证。长段持续移动和接触力控制没有因此自动具备。

## 安装与验证范围

- `deploy/flexiv/eef_chunk.py` 安装为独立采集器的 `collector/core/eef_chunk.py`。
- `deploy/flexiv/collector-eef-chunks.patch` 对现场已改采集器只添加短段独占、停止取消和反馈状态保护，不覆盖其他独立修改。
- RPent 环境服务新增显式 `--eef-chunk-control`；默认关闭。必须配合已安装的采集器路由和 `--supervised-control`。
- `move_eef` 只在实际能力标志开启时进入 RPC 与工具清单。
- 候选目录：`/home/zwy/work/embodied_harness/reviews/flexiv-eef-20261028/`。

离线替身验证覆盖：原有 MoveJ/轨迹行为、1/5 步同目标、段末保持、目标未到达的真实返回、字段/RPC一致、执行前拒绝、力/状态/相机/租约故障、SDK不明返回、保持超时与漂移、停止并发、不会在停止后补发目标，以及工作线程执行不阻塞操作员接口。

尚未进行物理动作烟测；真实节拍、停稳耗时、保持漂移和任务能力均未验证。用户尚在逐项审核提示，因此本次没有重启采集器、环境或 dashboard，也没有发起模型任务。

## 来源

- [GPT-as-Policy 单步契约](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/context/eef_control.md)
- [Flexiv 官方 v1.x NRT 笛卡尔示例](https://github.com/flexivrobotics/flexiv_rdk/blob/5338cc0316f34d7704be295bbc24b6e6f082de12/example_py/intermediate3_non_realtime_cartesian_pure_motion_control.py)：支持 1–100 Hz 命令频率，并展示保持指定 TCP 目标；本适配没有复制示例中的自动使能、回零或清故障。

## 验证结果（2026-10-28）

远程隔离候选使用实际 RPent .venv 执行：156 项通过（包含采集器硬件替身、原有控制回归、RPC/工具能力开关与字段、只读拒绝协议）。Ruff 检查与格式检查通过，CLI 帮助确认短段开关存在。控制器基线补丁仅在隔离副本中检查，当前服务源码和机械臂没有切换。

这些结果不包含真实机械臂动作或模型实验。
