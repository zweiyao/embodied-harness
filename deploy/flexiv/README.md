# Flexiv 原生关节复位接入

2026-10-26：用户要求参考采集工作台加快复位。旧复位每次只推进最多
0.0005 rad，再等待静止反馈；从本次起点到参考位需要上千次交互。

`collector-home-movej.patch` 是针对现场采集器独立修改的增量补丁，
应用前需核对基线；不覆盖采集器其他改动。RPent 的 `reset_home`
接收 `motion=MoveJ` 后轮询同一操作，不重复提交运动目标。

- 一次提交原生 MoveJ，速度使用采集器 `start_vel_scale`，仅接受 (0, 30]；现场为 30。
- 仅允许操作员已启用、独占租约、硬件正常且两路相机新鲜时开始/继续。
- 参考位核对机器人序号、配置关节和 FK，检查采样路径保留 4 mm 工作区余量。
  工作区检查不等于碰撞规划，操作员仍需确认回程无障碍。
- 使用 120 秒固定动作截止时间；不因轮询延长，不延长操作员授权。
- 控制器 `reachedTarget` 与实测关节误差 ≤0.0002 rad、速度 <0.005 rad/s
  同时满足才返回成功；异常由现有路由和 RPent 停止流程处理。
- 不调用采集器原 `go_to_start()`：它会张开夹爪，且原到位日志并未严格区分超时。
  此接口不发送夹爪命令，也不使能、清故障或自动恢复。
- MoveJ 模式只对当前拥有复位目标的租约开放；普通位姿动作不能在该模式执行。

硬件替身检查（不会连接设备）：

```bash
FLEXIV_HOME_SOURCE=/path/to/patched/collector/core \
  python -m pytest deploy/flexiv/test_home_movej.py tests/unit_tests/robots/flexiv -q
```

远程 60 项检查通过。部署后须由操作员重新启用，再进行实际复位；
测试通过不代表真机动作已完成。

## Native Cartesian target follow-up

Apply `collector-native-motion.patch` after the MoveJ patch above; compare the
current external source before applying. It adds `/rpent/supervised/pose-target`
while preserving the legacy small-step endpoint. Deploy the matching RPent
`motion.py`, `env_server.py`, toolkit and prompt together.

The new endpoint accepts one target within 50 mm / 10 degrees, calls the installed
RDK `SendCartesianMotionForce` once, and enforces 20 mm/s, 0.15 rad/s, 0.1 m/s²,
and 0.5 rad/s². RPent checks arrival from measured feedback; no generated target
is treated as proof of success. There is a fixed 35-second collector deadline
and a 30-second RPent feedback deadline. A separate stop-only RPC bypasses the
motion queue; other commands remain serialized. Camera/pose/joint feedback is
checked while motion is pending. These application checks are not hardware
emergency stops or whole-arm collision checking.

MoveJ's deadline is cleared only by its own completion logic. Gripper operations
cannot clear or replace an in-flight arm/home deadline. Feedback exceptions
attempt to stop, and expiry is checked even if hardware state reads fail.

```bash
FLEXIV_HOME_SOURCE=/path/to/patched/collector/core \
  python -m pytest deploy/flexiv/test_home_movej.py \
  deploy/flexiv/test_native_motion.py tests/unit_tests/robots/flexiv -q
```

Source references: [Flexiv NRT control modes](https://flexiv.us/software/rdk/manual/v2.x/control_modes.html)
and [RDK Cartesian command](https://devwebcom.flexiv.com/software/rdk/api/classflexiv_1_1rdk_1_1_robot.html).
The installed RDK 1.9 Python signature was inspected separately; acceleration
limits are passed by keyword. Fake-hardware checks do not establish actual
trajectory speed, stopping distance, or manipulation success.
