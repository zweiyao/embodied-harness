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


## 同配置第二轮

运行 `b9b163c4df5158154453` 于北京时间 16:25 结束，`budget_exhausted`，未完成插入。开始前实读 armed=true、夹爪就绪、无故障；实时画面确认 USB 已回到红色支架、蓝色槽为空。本对话仅提交相同任务，没有调整策略、工具、经验或追加控制。

两轮 config、profile、工具版本逐项一致，初始观测的标定哈希相同。机器人初始 TCP 位置差约 0.1005 mm，归一化四元数的姿态差约 0.0063°；物体由人工重新摆放，没有严格复现或测量物体初始位姿。现场画面的视角差异不应被当作机械臂初始姿态显著变化的证据。

| 指标 | 首轮 | 第二轮 |
| --- | --- | --- |
| 结果 | 画面支持插入并释放 | 抓取恢复后预算耗尽，未插入 |
| 总耗时 | 271.0 s | 374.7 s |
| 模型响应 | 20 | 25 |
| 工具调用 | 25 | 31 |
| 控制调用 | 12 | 16 |
| 定位调用 | 5 | 10（其中腕部 2 次失败） |

第二轮首次夹持试抬后 USB 未随动。模型反复调整抓取点和夹爪，之后尝试的两次腕部定位受 provisional side-only 规则拒绝，再改回侧面定位。最后张夹到 14 mm、4 mm 后抬升 35 mm，结束画面显示 USB 离开红色支架，但蓝色槽仍为空。没有进入插入阶段，也没有 finish(success)。这是决策预算耗尽，不是 3600 秒墙钟上限或网络错误。

Web session 的 succeeded 表示 planner 正常结束；任务结果以 outcome 的 budget_exhausted 及轨迹为准。第二轮 summary.actions=24 含 8 次成功定位，实际控制为 move_tcp 5、set_gripper 9、move_eef_delta 2，共 16 次。结束 IDLE、armed=false、无 fault；未自动再试、复位或松开夹爪。

两轮一成一败说明完整流程还不稳定，不能把上一轮成功解释为已经解决了鲁棒性。本轮失败集中于抓取与恢复效率，未提供第二次插入阶段的重复性证据。仍不能分离标定、经验、选点和物体重摆的影响。

本轮目录为同一 session 下的 `tasks/0002_flexiv`；检查摘要在 `/home/zwy/work/embodied_harness/validation/usb-board03-repeat-20261031/summary.json`。原始观测和 SDK 记录留在远程，`video_recorded=false`。[第二轮记录](http://127.0.0.1:18083/runs?id=b9b163c4df5158154453)。
