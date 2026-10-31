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

部署证据保存在远程 `validation/manual-calibration-20261031/`：切换前配置和状态、HID 已连接而机械臂未连接的状态、标定程序自检日志。页面 HTTP 200、双相机 connected、标定路由存在均已核验；尚未采集新棋盘数据或完成物理遥操作验证。
