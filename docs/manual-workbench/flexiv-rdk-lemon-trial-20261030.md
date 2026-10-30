# Flexiv RDK 柠檬放碗：首次任务连接检查

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
