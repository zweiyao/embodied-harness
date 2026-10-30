# Flexiv RDK：Astra USB 插入实验

2026-10-30，按用户要求将真机实验总时限改为 **3,600 秒**，改用远程
Codex SDK `gpt-6-astra / high`。机械臂现场启用后，只向 RPent 提交
“抓起 USB（U 盘）并插入蓝色插口。”，没有追加动作策略或手动接管。

## 配置与验证

- `control_mode=rdk`，25 次模型响应、16,384 输出 token；RDK 单动作 30 秒
  期限、控制器参数和工具保持原样。
- 远程持久入口 `harnessvla/local-setup/flexiv-dashboard.sh` 已配置
  `--planner codex --model gpt-6-astra --reasoning-effort high --planner-timeout-s 3600`。
  只重启 dashboard，机器人、相机及环境服务未重启。
- `bash -n`、活动进程参数、`/api/session/config` 与本轮
  `dashboard_config.json` 均核对通过。SDK 连接检查 14.064 秒返回 `ok`。
- 修改前配置备份于
  `embodied_harness/backups/flexiv-astra-usb-3600-20261030T143256/`。
  启动说明已提交 `7d106d2`，不是修改历史实验的 1,800 秒记录。

## 结果

本轮耗时 **381.0 秒**，完成 **25 次模型响应、30 次工具调用**，达到决策预算。
未触及 3,600 秒总时限。`finish=null`、`environment_success=null`、`error=null`；
网页“执行成功”仅代表框架没有抛出错误，不能据此认定插入成功。

SDK 终止事件为 `[agent] === turn 25/25 ===`，随后
`[codex-result] interrupted duration=379.7s`。30 次工具包括 11 次定位、
15 次 EEF 平移、1 次合爪，以及观察、读取标定、列目录各 1 次。
16 次控制均为单个原生命令，控制调用合计 32.66 秒；所有工具包含图像返回
共 51.94 秒。15 次平移到位误差平均 0.356 mm、最大约 1.000 mm。
2 mm 微调允许约 1 mm 到位误差，因此 `reached=true` 不能证明实际插入深度。

模型完成抓取、抬升 50 mm、搬运到蓝色插口附近并多次微调下探。夹爪闭合目标
1 mm，实测停在 3.50 mm / 19.24 N；随后图像可见 USB 随夹爪离开红色支座。
一次 2 mm 下探后，返回的基座系 Z 外力约 14.28 N；模型自行上退 3 mm 卸载，
反馈力回到接近零，再横移并尝试插入。最后一段下探的 Z 外力约 14.86 N。

最终图像仍显示夹持中的 USB 靠近孔口；没有张爪释放、可核验插入深度或
自动成功判分。本轮结论为 **抓取与搬运完成，插入是否完成未确认**。
接触力上升可能对应孔沿或其他接触，仅凭这些记录不能确定已插到底。

实验结束实读 `Mode.IDLE / armed=false / fault=false`，夹爪约
3.47 mm / 18.85 N，Z 外力约 13.70 N；未自动重新启用、继续下压或补做撤离。

## 用量与记录

SDK 报告累计输入 **1,688,486 token**（缓存 **1,592,576**），
输出 **5,228**（其中 reasoning output **1,496**）。这是累计用量，不是
单次上下文长度；没有账单，不据此估算美元费用。与上一轮 Qwen 柠檬任务不同，
不能把两轮耗时直接当作同任务模型对照。

远程原始目录：
`harnessvla/logs/20261030-14:32:56_dashboard_session/tasks/0001_flexiv/`。
保存配置快照、transcript、SDK 流事件、逐步状态、双路 RGB-D 与定位结果；
原生命令另记录在 `harnessvla/local-setup/flexiv-direct-rdk/rdk-actions.jsonl`。
原始数据和凭据不加入 Git。
