# 冻结工具测试：2026-11-03

用户授权开始测试。工具由当前 Codex 对话制作，远程 Astra high 只运行仿真策略。
使用开发第一版 `d6c13e920f4464898de3ad511749968989ee8cea84c67bfb458ec0582182bfa5`。

- 插管（任务1）、拔钥匙（任务2）各5轮，seed 0–4，依次运行。
- 60次模型响应、10000 token配置、单请求300秒、整轮3600秒；与开发配置一致。
- 沿用原生控制、observe/read_image/read_depth/tactile_stats/finish，并增加冻结感知工具。
- 工具、提示词、阈值和控制器保持冻结；基础设施错误留档并停止后续轮次，不自动补跑。
- 记录官方成功率、耗时、输入/输出/缓存token及工具调用；不把程序正常退出当成任务成功。

启动前工具版本、运行源码摘要及预算通过现有冻结入口校验。启动不等于测试完成，结果另行记录。
远程服务：`univtac-authored-frozen-test-20261103.service`。
完整记录目录：`/home/zwy/work/embodied_harness/experiments/univtac-authored-geometry-test-20261103`。
没有远程制作/评议请求，未进行Qwen测试。此前初始化偶发超时尚未根治，此批仍沿用原官方120秒初始化限制。
