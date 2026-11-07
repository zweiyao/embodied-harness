# Qwen v3 readable-memory screen at 600 seconds

The three approved candidate cells completed on two isolated LIBERO environments. Official success is **0/3 (0%)**. All three exhausted the full 600-second wall-clock budget; none exhausted the 30-request limit or ended through a model finish call. Finalization adds roughly 8–11 seconds to recorded elapsed time. No unexpected incident occurred in these corrected retries.

| Task (seed 0) | Official success | Elapsed s | Model requests | Action calls | Tool calls before first action | Mean returned model-request wait s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 0% | 610.1 | 18 | 4 | 5 | 32.7 |
| 4 | 0% | 610.6 | 18 | 2 | 22 | 30.2 |
| 8 | 0% | 608.4 | 25 | 2 | 14 | 23.9 |

All three attempted an action; the mean number of tool calls before the first action is 13.67 (n=3). Returned-request means exclude the single unfinished request at the end of each run. They include request transmission, provider processing and response reception, and are not pure network latency.

The 600-second budget allowed additional motion after the original 300-second window in tasks 0 and 4, but did not produce task success. This screen cannot isolate the effect of time, memory, or tools: there is no matched 300-second control for the corrected readable package, and only one seed per task. It does not demonstrate a success-rate or token benefit.

## Actual adoption and errors

- Task 0 successfully read next-action-evidence and object-relative-transfer. It called the container helper six times: five inconsistent-rim results and one measured result. There were four action calls and no release call before timeout.
- Tasks 4 and 8 successfully read all three approved note bodies. Task 4 made three depth-window queries with no valid samples and one file read targeting a directory; task 8 made one invalid segment call with the wrong prompt/point combination. These are model/tool-use failures within the evaluation, not infrastructure incidents.
- The batch sampling helper ran ten times across the three tasks, covering 38 points with zero per-point errors. This verifies execution and adoption, not task effectiveness.

## Exclusions and separate repair repeat

The first three v3 attempts were invalidated because the export placed notes under an unsupported extra memory/libero directory. Their events and outcomes remain remote. They are excluded from the denominator; see [incident report](memory-access-incident/report.md). The corrected independent package contains the same three note bodies at the corpus root with corresponding index paths. Permissions and system/user/guide text were preserved.

The separate v2 task-0 radius-repair repeat used unchanged v2 materials at 300 seconds and failed by timeout: five actions and ten calls before the first action. It is not pooled with the corrected v3 results. Earlier v2 episodes did not successfully read the new bodies, so they do not establish an accessible-new-memory condition.

## Proxy and latency verification

The two current start scripts explicitly unset HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and all three lowercase forms after environment activation and before Python execution. Inspection covered both workbenches and their model child processes, the batch controller, the original LIBERO workbench, and the user service manager: seven processes had no nonempty proxy variables; previous listeners 7900/17997 were closed. No active task or process was restarted for this audit.

A fresh short-text direct streaming request completed in **0.603925 seconds**, HTTP 200, with 30 input tokens and one output token. It contains no images or tools and cannot stand in for task latency. Prior transport tracing showed slow large-payload upload on the remote direct route; the Mac relay was only diagnosed and is not used in this batch. Evidence: [proxy audit](retry/proxy-audit.json), [short request](retry/direct-short-probe.json), and [prior transport study](../qwen-api-speed-20261107/report.md).

## Validation and cleanup

Remote full unit suite: 2009 passed / 15 skipped. Focused memory suite: 18 passed. Actual frozen-note reads: three succeeded; three write attempts were denied. Approved source/body hashes match; both generated helpers passed Docker preflight. Scoped pre-commit passed. Full pre-commit retains the same historical findings on the changed checkout and unmodified d366799; unrelated autofixes were discarded.

Final audit recomputed metrics, checked frozen materials/tool declarations/budgets, and verified protected source hashes. Both owned workbenches are stopped; original workbench identity, config and proxy-off network state are unchanged. Raw images/videos and credentials are not included in Git. Full records remain under `/home/zwy/work/embodied_harness/experiments/qwen-evidence-v3-screen3-retry-20261107`.

See [final verification](retry/final-verification.json), [results](retry/results.json), [preflight](retry/preflight.json), and [cleanup](retry/cleanup.json).
