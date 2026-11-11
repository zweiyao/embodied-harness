# RoboDojo 生命周期修复验证

已在远程独立副本实施两项分别获批的修改：按 runtime 守护进程来源传递 ENV 所有权，toolkit 仅关闭自己拥有的 ENV；客户端连接仅核对 metadata，不再隐式复位，dev 显式 reset 保留。

CPU 验证：RoboDojo 163 passed，全仓 2041 passed / 15 skipped，pre-commit、CLI 帮助和 diff 检查通过。只覆盖本机 Python 3.11，未代替完整 CI 矩阵。

真实仿真已能启动、生成场景并响应 RPC。eval-fair 模式下，借用 toolkit 关闭后 healthz 仍正常。拥有者发出的 env.close 已返回，但在 45 秒内未自行退出；父进程关闭管道后的清理退出码为 0，三个相机录像可读。保留该失败，不能把 GPU 生命周期整项标为通过。dev 修复后真实连接仅调用 env.get_env_meta，未触发 reset，借用关闭后 healthz 正常。显式 dev reset 的真实重复稳定性仍未验收。

独立环境还完成了两项额外依赖冲突处理、同一提交的 IsaacLab editable 安装，以及官方资源模板的纯路径生成。对齐既有 Codex 版本后全仓测试恢复通过，同时产生 packaging 与 Isaac Sim 固定版本的第九项元数据分歧；CPU 和启动检查不能推广为全面兼容保证。现有 Vulkan 兼容层只在诊断进程内启用，默认启动配置未改。

详见 [summary.json](summary.json)。原工作台和实际运行源码保持；不包含模型请求、任务动作或真机动作。日志、录像、观测和资产均留在远程验证目录，不进入 Git。

已用诊断堆栈定位拥有者退出阻塞：IsaacLab 的 STOP 回调持续 render，阻塞 SimulationApp.close。清理回调的具体补丁已在工作区 proposals/robodojo-stop-callback-20261112/ 准备，尚未获得批准或应用。
