# SpaceMouse 手动棋盘格标定

2026-10-31，为重新标定恢复原采集工作台。使用已有程序 `/home/zwy/work/flexiv/calibration/run.sh`，不新增机械臂控制器，也不替换当前 RPent 标定。

## 当前入口与所有权

- Mac 页面：`http://127.0.0.1:18081/`，SSH 本地转发至远程 `127.0.0.1:8081`。
- 远程采集后台：`127.0.0.1:9527`，只读采样接口 `/calibration/snapshot`。
- 已暂停 `harnessvla-flexiv-dashboard`、`harnessvla-flexiv-env`、`flexiv-rdk`、`flexiv-rgbd`，启动 `flexiv-collector`；避免两个服务争抢机械臂和相机。此时 RPent 真机网页 18083 暂不可用。
- SpaceMouse Wireless BT（256f:c63a）已通过现有 `/teleop/switch` 连接 HID；未连接或启用机械臂，未开始练习。练习开始时原程序会将遥操作目标同步至实测机械臂位姿。
- 腕部 260322279602、侧面 254522075549 均已连接，1280×720、30 FPS。

当前设置 `go_to_start=false`、`home_on_disconnect=false`。但原工作台的“连接机械臂”仍会初始化夹爪；“停止练习”仍会调用 `on_reset()` 回旧参考位，不能将这些选项理解为禁止所有自动运动。现场先妥善取下夹持物，再连接硬件；采样之间只松开鼠标停稳，不反复停止练习。退出练习前确认旧参考位的回程条件。

## 采样

现场在采集工作台连接机械臂并开始练习，用 SpaceMouse 摆姿态。棋盘与侧面相机固定，腕部相机看到完整棋盘；每次松手并停稳至少一秒后，在远程终端执行：

```sh
cd /home/zwy/work/flexiv/calibration
./run.sh capture --session sessions/board-03-20261031
```

新目录已准备，沿用 11×8 内角点、30 mm 方格参数；若棋盘尺寸变了，应先更新实测参数并使用另一新目录，不能混用。采集约 20–30 个位置和倾角不同的训练姿态，再额外采 5 个验证姿态：

```sh
./run.sh capture --session sessions/board-03-20261031 --holdout
```

检查所有角点图中的 ORIGIN 对应棋盘同一个物理角，再求解：

```sh
./run.sh solve --session sessions/board-03-20261031 --origins-checked
```

结果位于新目录的 `result.json`。该程序以 RGB 棋盘格与实测 TCP 求外参，不移动机械臂，不自动部署结果。未连接机械臂时接口返回 409 是预期状态，不应为绕过它自动启用。

## 恢复 RPent

先在现场结束手动控制，确认采集工作台已退出练习且停稳；不要在练习中直接停止采集服务，因为其退出路径可能触发复位。随后关闭采集后台，再启动 RDK、独立 RGB-D、Flexiv env 与 dashboard。恢复 `/home/zwy/work/embodied_harness/validation/manual-calibration-20261031/rpent-config.json` 中的模型、工具和预算。新标定另行检查后再更新 RPent；不要仅因为求解退出成功就自动替换旧结果。

部署证据保存在远程 `validation/manual-calibration-20261031/`：切换前配置和状态、HID 已连接而机械臂未连接的状态、标定程序自检日志。页面 HTTP 200、双相机 connected、标定路由存在均已核验；配置交接时尚未采集新棋盘数据；后续求解结果见下节。


## board-03 求解结果（2026-10-31）

已在远程运行上述 `solve --origins-checked`。共 30 帧：25 帧训练、5 帧独立验证。两帧腕部角点重投影超过采集程序的 1 px 门槛，按原规则排除，实际使用 23 帧训练和 5 帧验证。另有一帧侧面检测失败，该帧只参与腕部求解。角点预览的原点对应棋盘印字一侧的同一个物理角，未翻转或修改样本。

| 一致性残差 | 训练均值 / 最大值 | 独立验证均值 / 最大值 |
| --- | --- | --- |
| 腕部平移 | 2.278 / 5.290 mm | 2.460 / 3.125 mm |
| 腕部旋转 | 0.321 / 0.851° | 0.332 / 0.729° |
| 侧面平移 | 0.170 / 0.691 mm | 0.200 / 0.393 mm |
| 侧面旋转 | 0.015 / 0.069° | 0.024 / 0.049° |

现有检查要求所有有效样本均不超过 5 mm、2°。腕部只有训练样本 `sample-1793431768583151455` 的平移超过门槛，因此 `wrist_consistency_passed=false`，`side_consistency_passed=true`。求解器写出了诊断结果后报告检查失败；没有放宽门槛或按结果删除该样本。

超限帧的停稳位移为 0.043 mm、角点重投影为 0.247 px；全批停稳位移最大 0.110 mm。训练姿态旋转分布的奇异值为 1.401、0.777、0.305 rad，通过原程序的多轴姿态检查。现有记录不能确定超限的具体来源，也不支持直接认定为机械臂未停稳或角点顺序颠倒。

侧面外参使用腕部求出的基座到棋盘变换；其残差主要体现固定棋盘的重复观测稳定性，不能独立证明机器人基座中的绝对定位精度。腕部验证残差也不是 USB 孔口的实测定位误差。结果尚未通过完整一致性检查，未替换 RPent 的 board-02 标定，未移动机械臂或切换采集服务。

远程结果与证据：

- `/home/zwy/work/flexiv/calibration/sessions/board-03-20261031/result.json`
- `/home/zwy/work/embodied_harness/validation/manual-calibration-20261031/solve.log`
- 同目录 `solve-statistics.json`、`solve-diagnostics.json`

下一步应在任务区域补充独立定位核验，并针对超限姿态重新采样检查可重复性；保留本次样本和失败结论，不能仅靠重新划分训练/验证或删掉最大残差来宣布通过。


## 选用 board-03（2026-10-31）

按用户要求，远程 `flexiv-rgbd.service` 与 `harnessvla-flexiv-env.service` 的两份标定相关 drop-in 配置已改用 `sessions/board-03-20261031/result.json`。systemd 已重新加载配置；采集工作台仍在运行，RPent 真机服务仍停止，下一次启动时加载新结果。本次未切换硬件所有权或执行动作。

新旧结果的机器人、原生工具 TCP、相机内参相同。继续使用原 `tool_tcp.json` 的工具局部 +Z 8.37 mm 抓取补偿；这是之前确认的抓取参考，并非独立实测指尖长度。该文件及旧 board-02 结果的字节校验均保持一致。

新结果 SHA256：`540e8bd203f0a07ec8afa6f37823a0a8525bd49767bd5118c287951601cb7c18`。保留 `wrist_consistency_passed=false`、`side_consistency_passed=true` 和 `deployment_approved=false`。旧双相机现场确认绑定旧文件，故移除服务参数中的旧确认哈希，没有把该确认改写到新标定。沿用现有 provisional side control 配置：侧面可定位，腕部可观察，新标定尚无双相机现场验证记录。

远程实际 `Calibration` 加载成功，`test_perception.py` 为 24 passed；systemd 的有效启动参数已核对。备份、加载检查及测试日志在 `/home/zwy/work/embodied_harness/validation/activate-board03-20261031T075931Z/`。未做新标定下的实时相机或机械臂定位验证。
