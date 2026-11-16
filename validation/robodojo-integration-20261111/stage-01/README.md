# RoboDojo 第 1 项：独立环境与资源准备

状态：进行中，未完成验收。

已从 `5c57ad0` 建立独立远程源码副本和 Python 3.11.16 环境，固定 8 项 Git 依赖来源，核对资产和权重清单。608 项现有运行文件的保护检查未发现变化；没有启动仿真、模型或机器人实验。

cuRobo 已由原提交 `895c651` 的独立源码副本构建为 wheel，源文件没有修改，没有二进制扩展。构建在 RPent 项目外进行，避免本项目为其他 cuRobo 版本设置的全局 Torch 构建依赖；目标环境仍按原 RoboDojo 配方安装其运行依赖。wheel 文件与源码副本仅保留远程，摘要记录源码 commit 和 SHA256。

经用户确认，远程通过 Mac 现有代理的 SSH 反向转发下载资源。网络由独立 remote-network.sh 选择；安装器和下载脚本不设置代理或切换网络。没有更改 Mac 系统代理配置或启动远程代理核心。本次准备任务结束后，专门的清理监视已恢复远程直连并关闭本次 SSH 隧道。

首个 bottles 任务的 376 个资源文件已全部通过 SHA256 校验；外部 NVIDIA USD 引用仍待验证。全部 15,365 个 Assets 文件和 18 个 seed-0 checkpoint 推理文件已下载，并按清单核对文件大小；除首场景集合外尚未全量复核 SHA256。训练状态和训练数据不在下载范围内。

完整依赖闭包已解析为 411 项。最初的 367 项清单因安装覆盖项未保留 Isaac Sim 的 `all/extscache` 扩展而不完整，已被替代。当前显式保留所需扩展，25 项 Isaac Sim 发行包选择 NVIDIA 官方 Linux wheel，版本仍为 5.1.0.0；内核 wheel 已完整下载并验证 SHA256。安装器已使用 pip 26.3 的续传能力完成 uv 解析清单的安装，保留仓库已有依赖覆盖；`--no-deps` 用于避免 pip 再次解析已知冲突的上游元数据，不代表依赖或导入检查通过。

基础 RPent、runtime 和 Torch 导入通过，CUDA 可用。独立环境的 sse-starlette/wrapt 额外冲突已处理；按既有文档将同一提交的 IsaacLab 改为 editable 安装，并运行官方路径生成脚本产生两份 curobo.yml，未改变模板数值。现有 Vulkan 兼容层仅用于本次诊断进程，默认启动器未改。

真实场景已能初始化、响应 RPC，修改后的连接不再隐式复位；全仓 CPU 检查为 2041 passed / 15 skipped。对齐既有 Codex SDK 后新增 packaging 与 Isaac Sim 固定版本的元数据分歧，保留记录，不能据 CPU 与一次启动推断全面兼容。拥有者退出仍阻塞于固定 IsaacLab STOP 回调的 render 循环，另行草拟修复；第 1 项不标为全面验收完成。下载后远程已恢复直连，Mac 网络设置未改。


实际状态与证据见 [summary.json](summary.json)。操作日志、完整文件清单和未完成下载保留在远程 `validation/robodojo-integration-20261111/stage-01/`，不提交原始日志、权重或场景资源。阶段提交不创建 PR。
