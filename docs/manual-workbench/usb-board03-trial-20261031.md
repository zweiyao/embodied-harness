# USB 插入：board-03 标定首轮

2026-10-31 16:08–16:12（Asia/Shanghai），运行 `46968d5099eb52253c68`。任务为“抓起 U 盘并插入蓝色插口。”，RPent Astra high 自主执行，25 次决策、3600 秒上限；本对话未追加运动命令或策略干预。新 board-03 标定、原 +Z 8.37 mm 抓取补偿、现有经验与原生工具保持启动时配置。

## 结果与证据

模型以 `finish(success)` 结束；独立查看结束侧面画面，USB 在蓝色槽内直立，夹爪已张开并抬离。轨迹包括抓取后抬升、移动至槽口上方、分段下降 5/3/2 mm、张开到 30 mm、抬离约 50 mm。画面支持物理插入并释放的判断；未独立测量插入深度，也没有电气连接测试。

总时长 271.0 秒（SDK 269.5 秒），20 次模型响应、25 次工具调用。其中控制调用 12 次：move_tcp 2、move_eef_delta 7、set_gripper 3。汇总器 actions=17 还包含 5 次定位调用，不能把它直接称为 17 次机械臂动作。

模型主动读取经验目录及两篇插入经验，使用侧面定位 5 次；tactile_compare 未调用，虽然触觉图像随观测提供。本轮不能证明触觉工具增益，也不能从一次成功归因于重新标定。

真机没有独立自动任务判分，outcome.environment_success=null。现有汇总的 release_count=0、last_gripper_qpos=null、stable_placement=未独立验证与模型记录分别保留；释放依据为实际 set_gripper 调用、动作后图像及撤离后 USB 留在槽内。没有改写历史判分。

运行结束实读 armed=false、Mode.IDLE、fault=false。未自动复位或重复实验。

## 留档

远程完整目录：

`/home/zwy/work/embodied_harness/flexiv-runs/session-20261031-080400-4024104/tasks/0001_flexiv`

保存 prompts、SDK 事件、工具声明与源码快照、recipe、audit、多视角 RGB、深度、触觉与状态。`video_recorded=false`，本轮没有完整录像，不把保存帧描述为完整视频。复核记录位于 `/home/zwy/work/embodied_harness/validation/usb-board03-20261031/`。

[网页实验记录](http://127.0.0.1:18083/runs?id=46968d5099eb52253c68)。本提交仅保存小型文字摘要，不提交原始图像、运行数据或凭据。
