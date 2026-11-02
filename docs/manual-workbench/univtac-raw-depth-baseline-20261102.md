# UniVTAC 原始深度基线准备（2026-11-02）

状态：用户明确开始后，已于 2026-11-02 15:00（Asia/Shanghai）启动批次。
首轮为 insert_tube / seed 0，实验 ID `f4c67d3ca0e4ec5a3002`；尚无完成结果。

## 固定条件

- 页面任务 1：`insert_tube`；页面任务 2：`pull_out_key`。
- 每个任务 seed 0–4 各一次，共 10 次完整仿真，不做离线模型回放。
- Astra `gpt-6-astra`，Codex SDK，high；60 次模型响应，10000 token 配置，
  单请求超时 300 秒、整轮上限 3600 秒。保留现有原生控制器与官方判分。
- 感知：`observe`、`read_image`、`tactile_stats`、`read_depth`。
- 控制及结束：`move_eef`、`finish`。未选择 `depth_points` 或生成工具。
- 每轮新环境、新会话；批次内不调整工具或提示词，不自动补跑。
  seed 不等同于可恢复物理状态，此批只统计基线，不声称配对增益。

## 提示词与深度接口

系统提示词没有插管/拔钥匙的专属动作步骤、目标坐标或历史经验。
初始预抓取和无需释放的环境条件移至用户消息，官方 seen 任务文字不变。
工具声明只介绍参数、坐标和观测含义，不包含任务解法。

`read_depth` 保留原生米制深度 NPZ，并返回同分辨率预览。
预览是有明确最小/最大量程的 8-bit 灰度图，非法值为品红色；不冒充原始数组。
模型可选择至多 1024 个像素的矩形区域读取精确原始数值；不会平滑、上采样、
反投影或推断目标。浮点原始数据不修改，非法数值在 JSON 中表示为 null。

## 留档与统计

`examples/univtac/raw_depth_baseline.py` 通过原网页 API 顺序提交 10 轮。
配置、源码哈希和工具目录在批次启动时冻结；配置变化或服务重启会停止批次。
页面控制台可观看当前轮，历史记录保存原始事件、图像、视频和官方结果。

批次目录包含 protocol.json、status.json、results.json、results.csv 和 summary.json。
逐轮记录官方成功、终止原因、总耗时、planner 耗时、工具 handler 时间、决策数、
工具调用次数，以及供应商返回的累计输入/输出/缓存/推理 token。
不累加重复的累计 usage 事件。未报告字段为 null；缓存属于输入，推理属于输出，
不能再次相加。planner 耗时包含工具及 SDK 开销，不能当作纯网络延迟。
成功率分母固定为每任务 5 次，基础设施失败保留并另列；中途停止不得称为完成 10 次。
最终报告还需从逐轮结果汇总平均耗时和 token，并注明有效记录数。

批次已通过远程用户级 systemd 服务启动，等效命令为：

```bash
cd /home/zwy/work/harnessvla
PYTHONPATH=. .venv/bin/python examples/univtac/raw_depth_baseline.py \
  --url http://127.0.0.1:8093 \
  --output /home/zwy/work/embodied_harness/experiments/univtac-raw-depth-baseline-20261102
```

输出目录必须不存在，脚本不会覆盖旧批次。

## 已完成的检查

- 远程 `.venv` 中 UniVTAC 定向测试：276 passed，包括原始深度保真、非法值、
  工具选择、提示词环境条件隔离、usage 累计值和缺失字段。
- 完整测试（增加最后两个统计测试之前）：1818 passed、12 skipped、2 failed。
  两项失败为真机旧腕部定位限制测试，以及旧 pilot 的 maker/freeze 一致性测试；
  在单独进程加载修改前 toolkit 后仍得到同样两项失败，未修改无关逻辑。
- `pre-commit run --all-files` 通过；新增文件的定向 pre-commit 通过。
- 重启空闲 UniVTAC 网页后，目录包含 read_depth，实际配置为上面的 6 个工具。
- Astra SDK 最小连接检查返回 `ok`，耗时 20.058 秒；这不是仿真实验，
  不进入成功率或机器人任务耗时。
- 批次已启动；启动记录时首轮处于 task_starting，未得到任务成功率或工具增益结论。
- 托管服务：`rpent-univtac-raw-depth-baseline-20261102.service`。
  运行中配置或服务身份变化会停止提交后续轮次。
