# Historical Codex/Astra response-cycle estimate

Read-only analysis of the ten original empty-memory LIBERO tasks in
`experiments/libero10-task-no-memory-dual-20-20261107/astra/runs`.
All archived SDK requests name `gpt-6-astra`. This is not a measurement of the
current chat model or a new four-image API test.

For each episode, measure `turn/started` to `turn/completed`, subtract the union
of native `tool_request` to `tool_response` intervals clipped to the active turn,
and divide by strictly increasing cumulative token-usage updates. Tool intervals
were all paired; overlap was counted once. One byte-equivalent token-usage
notification in task5 was duplicated and excluded after inspection; all resulting
per-task counts match recorded `turns_used`. Initial strict counting detected
that duplicate rather than silently counting an extra model response.

230 response updates; 2059.347 seconds of non-tool active wall time; weighted mean
**8.954 seconds per response cycle**. Individual episode means range 7.176–10.897
seconds. Task0: 10.897 seconds (16 responses); task4: 7.906 seconds (30 responses).
The SDK terminal statuses are interrupted; the application interrupts turns for
its own finish/budget handling. This statistic does not reclassify task outcomes.

This is an estimate of non-tool decision-cycle overhead, not an observed HTTP
request/response duration or first-token latency. It includes client/MCP overhead,
network, server time and potentially an interrupted final response. External idle
waiting after turn completion is excluded. Historical Codex lacks the Qwen-style
`model_request`/`model_response` pair, so the old reports correctly left that
specific metric unavailable. This estimate does not replace that missing metric.

No same-payload Codex four-image probe was performed. Different endpoints, clients,
models, prompts, images and reasoning configurations prevent a controlled latency
ratio against recent Qwen tasks. Qwen diagnostics used enable_thinking=false,
which does not eliminate visual processing or other inference. WriteTimeout in
request-body transmission is client-side evidence, not a measure of model thinking.
The Mac Qwen PNG probe's first content at 14.386 seconds and completion at 15.131
seconds do not separate upload, queueing or vision prefill before first output.

OpenAI Docs distinguishes streamed agent-message deltas from turn completion:
https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
No new model calls, robot tasks, harness or network changes. Validation checked
paired tool intervals, deduplicated monotonic usage and exact agreement with all
ten archived turn counts; no implementation changed or unit suite was rerun.
