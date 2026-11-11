# 实验统计

实验列表、详情和控制台的结束摘要展示已有留档中的耗时、交互轮次和 token；详情同时展示开始与结束时间。统计读取每轮独立目录，不因服务重启丢失，也不会把上一轮的结果显示到新一轮。

- 开始时间：`manifest.json` 的 `started_at`；结束时间：`outcome.json` 的 `ended_at`。页面按浏览器本地时区显示。
- 耗时：`outcome.json` 的 `elapsed_s`，是运行器记录的秒数，包含模型等待和环境执行，不能当成纯模型延迟。
- 交互轮次：`outcome.stats.turns_used`，使用 planner 记录的模型响应/请求计数，不是工具调用次数。一轮响应可能包含多个工具调用。
- 总 token：`total_input_tokens + total_output_tokens`。缓存输入单独展示，但已包含在输入中，不能重复相加。这里是用量，不是账单费用。

缺失统计显示“未记录”，不算作零。异常终止时，用量可能只覆盖已返回统计的请求。旧的多 session 探索记录沿用其已保存的 `stats`，不把它解释为未留档的跨 session 累计值。完整原始字段仍保留在“结束状态与用量”中。

实验列表与详情的“任务指令（instruct）”读取该轮 `states.json` 中最早保存的非空
`steps[].extras.task_language`，缺失显示“未记录”。这里展示实际记录的指令，
不按任务编号查询当前基准，也不改写修正版任务的历史文字。

独立并行工作台的记录可通过服务端 `history_roots`（目录路径列表）只读索引。
每个目录采用与 `runs_root` 相同的 `*/tasks/*/dashboard_config.json` 布局；
原 `runs_root` 的链接保持不变，重复目录去重，其他机器人记录不混入。
该设置只影响历史浏览，不改变新实验输出目录、启动恢复范围或实验配置。
录像仍从原始目录读取，不复制实验数据。

## Qwen idle retry candidate

The server-owned LIBERO workbench option `api_idle_retry: true` enables an
isolated Qwen OpenAI Chat request policy. It is off by default and rejected for
other robots or planner profiles. With this option, `planner_timeout_s: 0`
explicitly disables the episode wall-clock limit; `max_turns` still bounds logical
model requests. Omitting the timeout retains the existing default timeout.

Each request allows 60 seconds without a nonempty reasoning, answer, refusal or
tool-function delta. Empty chunks do not reset the clock. The clock begins before
connection/upload and continues through streaming; a response can take longer
than 60 seconds while making progress. Connection failures, idle expiration and
streams ending without a terminal choice get one retry after two seconds. The
original transport is reused and inner SDK retries are disabled only on a copied
client for this candidate. No proxy or IP-family settings are changed.

Qwen thinking requests use `tool_choice=auto`, because the provider rejects
required or named tool choice in thinking mode. The local SDK output validator
still requires a successful `finish` tool call; plain completion text cannot
finish a task and remains subject to the logical request limit.

A complete response is buffered before it reaches the planner's tool scheduler.
A discarded attempt therefore cannot execute a tool, consume an additional
logical turn, or publish partial reasoning into the conversation. Streaming text
appears in the dashboard after completion; metadata-only `api_transport_attempt`
events record actual progress while waiting. External cancellation closes the
active stream and does not retry. Authentication and other non-transport errors
are not retried. Two failed attempts terminate the run as an infrastructure
incident, not a task-success observation.

Record transport attempts separately from `model_request` / `model_response`
events. Retries can incur provider charges even when the provider returns no
usage; normal token totals cover accepted responses and are not guaranteed to
include discarded attempts. A failed final logical request may still appear in
SDK request usage. Existing action/tool execution deadlines remain in force.
