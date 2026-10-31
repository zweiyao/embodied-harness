# Flexiv RDK 直连 / Direct RDK control

调用链为 **RPent → Env RPC → 独立 RDK HTTP 服务 → Flexiv RDK 1.x**。
机械臂和夹爪服务不导入采集器。独立 RealSense 进程提供原子 RGB-D 文件，
原有标定、动作后图像、深度、工具结果和实验记录继续由 RPent 保存。

2026-10-30 已在现场主机完成只读部署检查：旧采集器停止，RPent 经新服务读到
真实 TCP/关节/力反馈及 side、wrist 两路 RGB-D。机械臂保持 IDLE、未启用，
未执行运动或夹爪开合；物理到位、停止与抓取效果仍需后续现场实验验证。

## 启动

RDK 服务使用安装了现场 `flexivrdk` 的 Python 环境；当前接入按 RDK 1.9.0
核对。依赖 FastAPI、Uvicorn、Pydantic 2、NumPy、SciPy。相机进程另外需要
`pyrealsense2`。包导入不加载 SDK；也可直接执行对应 `.py` 文件。

1. 停止旧采集器的机器人和相机进程，避免两套程序拥有同一硬件。
2. 复制 [rdk-server.example.json](../../deploy/flexiv/rdk-server.example.json)，填写
   机器人序列号、实际工作区和日志路径。工作区检查只针对 TCP，不是碰撞规划。
3. 分别启动三个服务：

```bash
python -m robots.flexiv.rdk_server --config /path/rdk-server.json --port 5000

python -m robots.flexiv.rgbd_camera \
  --calibration-file /path/result.json --output-dir /dev/shm/rpent-flexiv/rgbd

python -m robots.flexiv.env_server --backend rdk \
  --rdk-endpoint http://127.0.0.1:5000 --port 8084 \
  --calibration-file /path/result.json --tool-tcp-file /path/tool_tcp.json \
  --rgbd-dir /dev/shm/rpent-flexiv/rgbd
```

相机保留标定对应的彩色分辨率。默认先检查设备是否支持 640×480 深度，
不支持时使用其彩色分辨率；也可成对指定 `--depth-width/--depth-height`。
现场 D435 使用原生 640×480 深度，D405 使用原生 1280×720 深度，均由
RealSense 对齐到 1280×720 彩色图。记录保留原生深度尺寸，不将对齐后的
尺寸当作原生深度分辨率。

侧面和腕部均支持只读定位；选择可见特征更清楚、深度有效的视角，
并在估计不一致时交叉检查。原始标定检查结果随定位返回，不限制相机选择。
已有现场确认的标定可继续使用 `--allow-provisional-side-control` 与
`--operator-confirmed-calibration-sha256`；原始验证结果和确认来源均保留。
不要给 RDK 后端传旧的 `--supervised-control` 或 `--eef-chunk-control`。

Dashboard 使用：

```bash
export RPENT_FLEXIV_RDK_ENDPOINT=http://127.0.0.1:5000
rpent --robot flexiv --control-mode rdk --env-endpoint http://127.0.0.1:8084 \
  --dashboard --dashboard-host 127.0.0.1 --dashboard-port 8083 \
  --planner codex --model gpt-6-astra --reasoning-effort high --max-turns 25 \
  --planner-timeout-s 3600
```

当前现场实验总时限为 3,600 秒；`max_turns=25` 限制模型响应次数，不是工具调用
总数。总时限与 RDK 单动作 30 秒期限分别配置。`GET /api/session/config` 可核对
当前实验预算；现场启动脚本须保留该参数，服务重启后才会沿用。

启动不会使能、初始化夹爪、复位或移动。页面“启用机械臂（RDK）”调用 `/enable`，
绑定已有夹爪并进入原生笛卡尔模式。故障清除、夹爪全行程初始化和复位不自动执行。
实验结束调用 `/stop`；下一次实验前重新启用。部署时用 systemd `Conflicts=`
互斥旧采集器；服务器自身另有按机器人序列号区分的进程锁。

## HTTP 接口

默认只绑定 `127.0.0.1:5000`；下面是远程主机上执行的 curl 示例。
`/docs` 提供实际 OpenAPI 参数。除 `/health`、`/state`、`/home-preview` 为 GET，其余均为 POST。

| 接口 | 输入/作用 |
| --- | --- |
| `/health` | 服务连接状态 |
| `/state` | TCP、关节角/速度、TCP速度、原生外力/力矩、夹爪、工具和控制配置 |
| `/enable` | 操作员启用机械臂，绑定已有夹爪；不清故障、不复位 |
| `/activate_gripper` | 绑定/启用配置的夹爪；不执行全行程 `Init()` |
| `/pose` | `position_m`，可选 `quaternion_wxyz`；原生轨迹到位后返回 |
| `/delta` | `translation_m`、`rotation_vector_rad`；从当前TCP解析一次增量目标 |
| `/move_gripper` | `width_m`；一次原生开度命令，返回实测开度与力 |
| `/stop` | 中断当前命令并停止机械臂和夹爪，撤销启用 |
| `/home-preview` | GET：查看保存的参考关节/TCP、当前状态和复位参数；不运动 |
| `/jointreset` | POST：一次原生 MoveJ 回保存关节参考，到位后完全张开夹爪 |

## 网页工具简介

开始页和控制台的“工具简介与源码”共用仿真的 `/tools` 页面、`/api/tools`
接口和工具卡片，按控制、感知、运行辅助分组，展示用途、参数与源码。
启动页可为每轮选择兼容工具，源码和版本随实验冻结；访问目录不会连接、启用或移动机械臂。

目录使用与 `FlexivToolkit` 注册相同的模式选择逻辑，展示当前控制模式支持的接口。
启动时核对所选工具的版本、依赖与当前启用／标定状态，不可用时明确报错。
目录覆盖 RPent 注册工具，不包含 Codex SDK 等规划器的内置能力。
RDK 模式的网页复位属于操作员接口，不作为模型工具显示。

选择与执行使用 dashboard 的 `RPENT_WORKBENCH` 配置，其中 `library_root` 指向
感知工具版本库，`runs_root` 指向实验记录目录。旧变量 `RPENT_FLEXIV_TOOL_LIBRARY`
仅用于未启用工作台时的只读展示，不能单独开启实验工具选择。
目录复用版本库的哈希校验，只读取源码及元数据，不在主机执行生成代码。
`sensor_alignment_contact` 已接入 `flexiv.alignment.v1` 记录适配器，依赖
`localize_target` 返回的 `record_step` 查询编号；源图像编号仍是 `step`。
满足相同输入契约的其他程序可复用该适配器。其他未接入真机执行器的工具仍显示
不兼容原因。未选工具不会注册给模型，原生动作后的图像仍自动返回。回放状态单独展示，不表示
已取得任务增益。

## 网页复位

在 RDK 配置中设置 `home_reference` 为操作员保存的参考 JSON 路径；未配置时
复位不可用。文件沿用既有 `captured_state` 格式：`robot_sn`、七维弧度
`joint_position`、七维 `tcp_pose`、`coordinate_frame="robot_base"`、
`quaternion_order="wxyz"`。启动时验证并冻结文件内容与 SHA256，修改文件须重启
RDK 服务才会生效。参考 TCP 必须在配置工作区内。

开始页和控制台均提供“复位（回参考位并张开夹爪）”。机械臂已启用且模型空闲时可点击，
页面先显示参考目标、当前受力与夹爪，再由现场操作员确认工件已退出槽口、回程
无障碍。按钮不自动启用、不清故障；实验运行和复位互斥，“停止”
始终可以中断复位。复位使用保存的关节目标，不是按 100 mm 笛卡尔限制拆段。
没有自动退离接触或路径碰撞检测，保存文件也没有记录旧工具的 TCP 配置。

执行为一次 `MoveJ`、`jntVelScale=30`，使用现有 `timeout_s` 截止时间。
原生到位标志、实测关节误差≤0.0002 rad和关节速度<0.005 rad/s必须同时满足，
并核对最终 TCP 与参考位姿在现有到位容差内。到位后恢复 Cartesian 模式，随后以设备最大开度张开夹爪。两阶段共用操作锁与停止取消状态；
夹爪未到位不报告复位完成。成功后保留启用状态；异常/超时停止并撤销启用。停止后的旧请求不会补发命令。
该接口只用于现场操作员按钮，不加入模型工具清单。

```bash
curl -s http://127.0.0.1:5000/home-preview
# 现场启用并确认回程后执行；不接受临时目标或速度参数。
curl -X POST http://127.0.0.1:5000/jointreset
```

```bash
curl -s http://127.0.0.1:5000/state
curl -X POST http://127.0.0.1:5000/activate_gripper

# 以下请求会实际执行；在现场启用并确认目标后调用。
curl -X POST http://127.0.0.1:5000/enable
curl -X POST http://127.0.0.1:5000/delta \
  -H 'Content-Type: application/json' \
  -d '{"translation_m":[0.02,0,0],"rotation_vector_rad":[0,0,0]}'
curl -X POST http://127.0.0.1:5000/move_gripper \
  -H 'Content-Type: application/json' -d '{"width_m":0.05}'
curl -X POST http://127.0.0.1:5000/stop
```

`/state` 的 `ext_wrench_in_world` 和 `ext_wrench_in_tcp` 分别保留 RDK 世界系与
TCP系语义，数组前三项为力、后三项为力矩。不要将两者混用。

## 动作语义与剩余检查

RDK 模式的模型工具是 `move_tcp(position_m, quaternion_wxyz)`、
`move_eef_delta(translation_m, rotation_vector_rad)`、`set_gripper(width_m)`、
`stop_motion()`，以及既有观察/定位工具。模型没有启用、清故障或初始化工具。
共享系统提示词不修改；通过机器人自己的 PromptBundle 添加简洁的 RDK 模式。

- 基座坐标、米、wxyz。增量旋转为基座轴旋转向量，左乘当前姿态；不是欧拉角。
- 每次运动只发送一个原生目标并等待实测到位，**没有 steps 参数或200 ms截断**，
  不在段末把目标替换成当前位置，也不拆成1–2 mm步。
- 示例配置：单次目标100 mm/30°，线速度20 mm/s、角速度0.15 rad/s，
  加速度0.1 m/s²和0.5 rad/s²；到位阈值1 mm/0.5°且关节速度<0.005 rad/s，
  命令超时30秒。这些都是真机配置，不从模型参数中覆盖。
- 保留有限数值/单位四元数、目标工作区/增量上限、单命令互斥、硬件状态和命令超时。
  执行异常会停止；可确定尚未执行的参数错误仅拒绝该请求。
- 无采集器租约、30分钟授权时限、4 mm边界余量、桌面旋转50 mm规则、
  40 ms节拍迟到停机、按相机帧龄停机或额外22 N夹爪反馈停机。
- 夹爪一次 `Move`，由原生力限制执行；返回 `reached`、`stopped_short`、
  原始力反馈。未到位但静止0.5秒时，明确停止夹爪并返回
  `stationary_before_target`，不停止整臂；没有旧的5 N接触截断或2 mm分段。
  静止、受力和命令返回均不证明抓取成功。
- RGB-D仍核对真实内参与时序；标定几何需要静止采样。不满足时拒绝对应观测，
  不把失效图像/变换冒充有效数据。相机检查不在RDK运动线程中执行。
- 不修改设备已配置的阻抗，也不替代非夕固件的急停和内部保护。

审计路径保存命令、实测状态、返回和错误，逐行写入。RPent保存模型调用、
动作后图像/深度及实验结果。日志与设备配置不提交Git。

## English

The direct backend runs **RPent → Env RPC → standalone HTTP server → Flexiv RDK
1.x**. It has no collector imports or control/session routes. A separate
RealSense process publishes real color-aligned RGB-D frames; RPent retains
calibration, images, tool results and experiment records.

Startup connects read-only. Explicit `/enable` binds the existing gripper and
selects Cartesian mode without homing, fault clearing or gripper initialization.
`/activate_gripper` binds the device; it does not call full-stroke `Init()`.
Pose and base-frame delta requests send one native target and await measured
arrival. There is no 200 ms truncation, intermediate hold target or tiny-step
gripper loop. Actual limits are reported in `/state`; the table and example above
describe their defaults. Stop interrupts active work, disarms, and cannot be
undone by a cancelled worker. Experiment close stops the devices.

Use `--control-mode rdk` and set `RPENT_FLEXIV_RDK_ENDPOINT` for the Dashboard
operator controls. Legacy collector modes retain their existing contracts.
The deployed episode limit is 3,600 seconds (`--planner-timeout-s 3600`), with
25 model turns. This does not change the separate 30-second RDK command deadline.
Keep the planner flag in the service launch script and verify its active value
through `GET /api/session/config` after a restart.
Set optional `home_reference` to a saved reference JSON containing the original
`captured_state` robot identity, seven joint positions in radians, base-frame TCP
pose and wxyz quaternion order. The server validates and freezes the reference at
startup. `GET /home-preview` is read-only; operator-only `POST /jointreset` submits
one native MoveJ with velocity scale 30, then opens the gripper to its native maximum. It
requires an enabled robot, verifies native arrival plus measured joints, quiet
joint velocity and saved TCP agreement, then restores Cartesian mode before opening the gripper. Both stages share the command
lock and stop cancellation scope; an incomplete opening fails the reset. The existing
command timeout applies. Error or stop disarms; a cancelled worker cannot restore
the mode or resend motion. No auto-enable, contact retreat or collision checking
is added. The saved file does not contain the old native tool TCP configuration.

The setup page and console show the reset button and a return-path confirmation.
Planner tasks and operator reset are mutually exclusive; Stop remains available.
Reset is not exposed as a planner tool. With no configured reference the button
is unavailable. Changing the reference file requires an RDK service restart.

Only one program should own robot/cameras. The CLI process lock prevents duplicate
copies of this server; deployment service conflicts exclude the old collector.
External SDK programs are outside that lock. Native fault checks, configured
workspace/target bounds, finite inputs and fixed command deadlines remain;
camera freshness no longer stops native motion. Calibrated observations still
require valid synchronized frames and stationary capture.

The setup page and console link to the shared `/tools` catalog used by simulation.
The setup page selects compatible tools for each run and freezes their source and
versions. Unselected tools are absent from both planner declarations and dispatch;
native images after actions remain unchanged. Descriptions, parameters and source
come from tool declarations. Browsing does not open robot resources. The catalog
covers RPent tools, not planner SDK built-ins.
Selection and execution use the Dashboard's `RPENT_WORKBENCH` configuration, with
`library_root` for the versioned perception library and `runs_root` for experiment
records. The legacy `RPENT_FLEXIV_TOOL_LIBRARY` variable only enables read-only
browsing when no workbench is configured. The `flexiv.alignment.v1` input adapter connects `sensor_alignment_contact`
and other programs with the same contract to measured recorded frames and the
existing isolated Docker executor. `localize_target` returns both source-image
`step` and localization-query `record_step`. Unsupported adapters remain unavailable
with an explicit reason. Replay validation does not establish task improvement.

Verification uses fake hardware and loopback HTTP before any explicitly started
physical trial. Passing these checks does not establish physical task success.

References: [RDK control modes](https://devwebcom.flexiv.com/software/rdk/manual/control_modes.html),
[RDK v1 Robot](https://github.com/flexivrobotics/flexiv_rdk/blob/v1.x/include/flexiv/rdk/robot.hpp),
[RDK v1 Gripper](https://github.com/flexivrobotics/flexiv_rdk/blob/v1.x/include/flexiv/rdk/gripper.hpp).
