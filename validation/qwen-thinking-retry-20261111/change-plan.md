# Approved thinking and idle-retry candidate

User authorized revising retry behavior and one Qwen Flash thinking-enabled
LIBERO task-0 trial. The earlier proposal retains 30 logical requests, removes
the episode wall-clock limit, and retries one stalled request after two seconds.
Effective progress means a nonempty reasoning, answer/refusal or tool-function
delta; empty heartbeat chunks do not reset the 60-second idle clock. Upload and
first-output waiting are included. Action deadlines remain unchanged.

The isolated candidate adds `rpent/planner/api_idle_retry.py`, with default-off
wiring in `api_loop.py`, `base.py`, `dashboard/workbench.py`,
`dashboard/state.py`, and `cli/dashboard.py`. Server-owned `api_idle_retry=true`
allows this LIBERO Qwen profile to set `planner_timeout_s=0`; absence preserves
existing defaults. Model profile reasoning changes from none to medium, which
this Qwen adapter translates to `enable_thinking=true` (a boolean, not a calibrated
medium intensity). Memory, native tools, image format, selected tool versions,
seed, input task and the 16384 output-token budget are preserved.

The transport client copy disables inner SDK retries, reuses the existing HTTP
transport and inherits networking. No proxy/IP-family changes are made. Complete
responses are buffered before tool scheduling, so discarded partial tool calls
cannot execute. Failed transport attempts have separate metadata-only events and
do not add a successful logical turn. External cancellation never retries.
Retry exhaustion is an infrastructure incident; authentication/parameter errors
are not retried. Provider billing may include discarded attempts without usage.

The initial trial exposed a provider HTTP 400 on `tool_choice=required` with
thinking. It executed zero actions and is preserved/excluded. The corrected
candidate sends `auto` for thinking requests while keeping the local finish-only
output validator. Added SDK tests prove plain text cannot finish the task and
repeated plain text still exhausts the 30-request budget. The initial source
checkout remains intact; the corrected candidate uses a separate v2 checkout.

Validation: real installed SDK through an offline HTTPX2 mock transport, including
continuous thinking longer than the scaled idle threshold, partial tool-call
cancellation, byte-identical retry bodies, no duplicate tool execution, 30-turn
cap, two failed attempts, empty heartbeat and incomplete-EOF behavior,
authentication rejection, external cancellation, and actual serialized
thinking/tool-choice parameters. Full unit suites and scoped pre-commit run on
the remote candidate; historical unrelated lint/format failures are retained and
hook mutations restored. One corrected task trial follows software checks.
The continuous optimization loop remains paused; no new task batch is authorized.
