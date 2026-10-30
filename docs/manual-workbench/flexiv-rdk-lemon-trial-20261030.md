# Flexiv RDK 柠檬放碗：Astra 连接失败与 Qwen 真机验证

最新结果：Qwen3.8 Max 自主完成了柠檬抓取与放入碗中，随后撤离过程中触发
1,800 秒规划超时。实物放置完成与框架超时退出分别记录；没有自动成功判分。

## Astra 连接尝试

2026-10-30，操作员确认物品和路径并启用后，向原 RPent 提交唯一任务：
“夹起柠檬并放入碗中。”未追加动作策略、未手动接管动作。

配置为 `control_mode=rdk`、远程 Codex SDK `gpt-6-astra`、reasoning high、
25 次决策、16,384 输出 token、1,800 秒规划上限；控制代码为 `0c9ddbf`。
启用后实读 Cartesian 模式、armed=true、gripper_ready=true、fault=false，
初始夹爪约 25.05 mm / 0.82 N。

## 结果

- 任务记录耗时 44.2 秒；模型连接阶段返回 `workspace routing discovery failed`。
- 模型决策、工具调用、输入/输出 token 均为 0；没有机械臂运动或夹爪开合。
- 实验结束后服务停止并撤销启用：IDLE、armed=false、fault=false。
- 初始双相机 RGB、深度、标定、transcript、SDK 重连事件已留档。

这是基础设施失败，不是抓取失败，也未验证新 RDK 后端的物理动作效果。

远程记录：
`harnessvla/logs/20261030-10:19:57_dashboard_session/tasks/0001_flexiv/`。
原始记录、图像、设备配置和凭据不加入 Git。

## 连接诊断

不附带硬件工具的 SDK 最小请求在 25.019 秒后超时。实际 Dashboard 与 SDK
使用远程 `127.0.0.1:7900` 代理，本地硬件端点直连；SDK/CLI 为 0.162.1。
同一代理访问 ChatGPT 和认证端点发生 TLS `SSL_ERROR_SYSCALL`，访问 GitHub
也发生上游断连；远程直接连接 ChatGPT 超时。Clash 当前节点“美国 01”与
同地区既有备选“美国 02”的公开 HTTPS 测速均返回 503，无有效延迟；未切换
节点。已确认失败不限于机器人 MCP 工具，尚不能确定节点失效的内部原因。
等待远程代理恢复后先复核 SDK；未更换模型或自动重新启用机械臂。

## Qwen3.8 Max 真机尝试

用户随后要求先使用 Qwen。复用 LIBERO 的既有 Aliyun API 与服务器凭据文件，
使用 `api / openai-chat:qwen3.8-max`，取消该 dashboard 进程的代理变量。
`reasoning_effort=high` 在 API planner 中映射为 `enable_thinking=true`，
不代表与 Codex high 相同的推理预算。保留 25 次模型响应、16,384 输出 token、
1,800 秒规划上限，控制实现、参数和机器人提示不变。只重启 dashboard，
RDK、相机及环境服务未重启。配置备份保存在远程
`embodied_harness/backups/flexiv-qwen-rdk-20261030T110223/`。

独立直连检查 1.654 秒、实际 dashboard 连接检查 2.518 秒，均返回 ok。
现场操作员启用后，实读 armed=true、gripper_ready=true、fault=false，提交同一句
“夹起柠檬并放入碗中。”。没有追加抓取策略、修改运行配置或手动接管动作。

### 实物与终止结果

- 第一次合爪为空抓，Qwen 从图像识别后自行张开，横向修正后重新抓取。
- step15 夹爪目标 20 mm，实测停在 49.79 mm、约 19.37 N；返回
  `stopped_short=true / stationary_before_target`，没有停止机械臂或整轮任务。
  随后 step16 抬升 70 mm，侧面图像证实柠檬离桌，才确认抓取成立。
- 搬运后有多次放置位置修正。step25 张开到 90.11 mm；最终 side/26 图像可见
  柠檬留在碗中、夹爪张开且空着，模型也报告柠檬在碗内。
- 随后的 step26 请求向上撤离 80 mm，在执行约 0.63 秒后被总超时清理取消，
  返回 `Command cancelled by stop`，没有完成整个撤离目标。
- transcript：耗时 **1,802.5 秒**，错误 `planner timed out after 1800s`，
  `finish=null`、`environment_success=null`。网页“运行失败”表示流程超时，
  不能据此否认已观察到的实物放置，也不能把实物放置改写为自动判分成功。
- 结束后实读 **Mode.IDLE、armed=false、fault=false**，夹爪约 90.07 mm。
  未重新启用或补做撤离。

### 调用与限制

记录 24 次已完成模型响应、27 次进入 RPent 的工具调用：14 次 EEF 增量、
5 次夹爪、7 次定位、1 次观察。一次模型响应可以包含多个调用，因此工具数
不是决策数。另有一次未声明的 `get_tcp_pose` 调用被 API 框架拒绝，不进入
上述执行计数；Qwen 随后改用已提供的增量接口。

14 次 EEF 增量中，12 次单命令到位，1 次超出配置工作区而在发送前拒绝，
1 次撤离被总超时取消。到位段包含约 37 mm / 2.24 秒、70 mm / 3.75 秒、
93 mm / 4.95 秒，证实新接口可以执行完整目标，未再按旧接口的 200 ms 截断。
12 段到位位置误差平均 0.326 mm、最大 0.965 mm。19 次控制调用（包括两次
错误返回）合计 45.54 秒；其余 1,756.96 秒包括模型、感知、图像与留档开销。
这是一轮接口与任务可行性验证，不是模型或工具增益对照。

API 报告累计输入 **2,200,650** token（其中 cached input **1,566,976**）、
输出 **52,712** token。累计输入包含多次请求重复携带的历史，不是单请求
上下文长度；未取得账单，不估算金额。当前真机路径没有逐请求开始/结束日志，
不能把总时间减去动作时间当作纯模型推理或网络延迟。

本轮主要未解决项是抓取初始偏移、放置阶段反复判断、一次未声明工具调用，
以及未在预算内完成撤离与结束。Qwen 对“相机偏差”的文字解释只是模型假设，
本轮没有独立标定证据，不直接归因为标定错误。

远程完整记录：
`harnessvla/logs/20261030-11:02:38_dashboard_session/tasks/0001_flexiv/`。
其中包含 transcript、states、逐步双路 RGB/深度和定位结果；原生命令审计在
`harnessvla/local-setup/flexiv-direct-rdk/rdk-actions.jsonl`。原始记录与凭据不加入 Git。
