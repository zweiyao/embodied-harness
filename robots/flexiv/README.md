# Flexiv 接入 / Flexiv integration

本适配器将 RPent 接入已有的 Flexiv 采集器，复用其机械臂、夹爪和相机连接。
采集器是独立部署的外部服务，本仓库不包含它的实现、Flexiv SDK、设备配置、
相机标定数据或模型权重。仅克隆此仓库不能独立启动整套真机系统。

## 接口与依赖

调用链：RPent Toolkit → Flexiv EnvClient → RPent RPC → 采集器 HTTP → Flexiv RDK。
采集器默认地址为 `http://127.0.0.1:9527`。它必须实现适配器使用的
`/rpent/connect`、`/rpent/observation`、`/rpent/close`、`/rpent/supervised/*`
及 `/rpent/operator/*` 接口。具体请求与返回字段见
[env_server.py](env_server.py)、[motion.py](motion.py) 和 [operator_ui.py](operator_ui.py)。

在项目根目录安装基础依赖与离线测试依赖：

```bash
python -m pip install -e '.[test]'
```

外部采集器准备完成后，可通过 `python -m robots.flexiv.env_server --help`
查看环境服务参数。下面是读取已有标定与 RGB-D 数据的服务配置示例；路径需要
替换为实际部署路径：

```bash
python -m robots.flexiv.env_server --port 8084 \
  --collector-endpoint http://127.0.0.1:9527 \
  --calibration-file /path/to/calibration/result.json \
  --tool-tcp-file /path/to/tool_tcp.json \
  --rgbd-dir /path/to/collector/rgbd
```

这三个数据路径必须一起提供。上述标定模式不启用受限动作；动作模式需要
显式指定 `--supervised-control`、`--control-log-dir`，并由操作员授权。
`--reset-before-task` 默认关闭。实际标定有效性由部署现场验证。

RPent 使用 `--robot flexiv --env-endpoint http://127.0.0.1:8084` 连接该服务；
模型、API 地址与凭据按照上游 Planner 文档配置。不要将密钥写入仓库。

## 控制台

Dashboard 支持开始页、模型选择、下一任务预算设置及真机停止按钮。
`RPENT_DASHBOARD_SETUP` 指向现场部署的开始页 JSON 配置；未设置时直接显示控制台。
`RPENT_FLEXIV_COLLECTOR` 指定操作员按钮使用的采集器地址，必须与环境服务一致。
部署配置和 systemd 服务文件由现场维护，不随源码上传。

任务示例：

```text
/rpent-task "只观察机械臂和相机状态，不移动机械臂或夹爪。"
```

## 动作与观测约定

- `observe` 保存真实位姿、图像、深度与标定信息；动作后自动记录观测。
- `view_perception_setup` 和 `localize_target` 使用已记录帧的标定与深度。
- 坐标使用机器人基座系、米，四元数为 wxyz；侧装机械臂的基座 +Z 不代表重力向上。
- `move_tcp` 每次调用最多 50 mm / 10°，拆成反馈驱动的小步；
  `move_delta` 入口最多 2 mm。夹爪闭合接触不等同于确认抓取成功。
- `align_tool_down` 使用标定桌面法向，并要求夹爪张开与桌面间隙满足检查条件。
- `reset_home` 使用操作员保存的关节参考位姿，需明确授权并检查路径；
  自动任务前复位默认关闭。路径边界检查不是完整的机械臂碰撞规划。
- 停止和中断会停止动作；模型不能启用动作、清故障或初始化设备。
- 当前适配器不包含 Flexiv VLA、碰撞规划器或物理任务成功判定器；
  模型的完成声明不能代替实际成功判定。

现场相机外参、工具补偿、工作区和复位参考数据都需要独立配置与验证。
原始触觉接入和自动生成感知工具不属于当前这份已实现的适配范围。

## 离线验证

```bash
python -m pytest tests/unit_tests/robots/flexiv -q
```

这些测试使用离线替身验证接口行为，不驱动机器人，也不证明真机任务成功。
日志、标定数据、实验计划与验证看板记录均保留在部署环境，未包含在此代码快照中。

## English

This adapter connects RPent to an externally deployed Flexiv collector, which owns
robot, gripper and camera connections. The collector implementation, vendor SDK,
device configuration, calibration files and model weights are not bundled.
Cloning this repository alone does not reproduce the complete hardware system.

The commands above configure calibrated observation. Supervised motion requires
explicit server options and operator arming; automatic reset is disabled by default.
Coordinates are robot-base metres with wxyz quaternions. Calibration, workspace,
tool offsets and saved home joints require deployment-specific validation.
There is no Flexiv VLA, collision planner or native task-success evaluator in this
adapter. Offline tests validate interfaces without moving hardware. Local experiment
records and the validation dashboard are excluded from this source snapshot.
