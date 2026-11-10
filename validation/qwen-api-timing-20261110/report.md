# Qwen Flash call timing, 2026-11-10

Read-only reanalysis of iteration-09/10/11 task0/4 events. Request-to-response
sums agree with the saved metrics within 1 ms. These spans include client/SDK
work, transport, queueing and inference, not pure model compute. Interrupted
final requests are excluded from completed-response averages.

| Iteration | Task | Completed responses | Mean wait (s) | Max wait (s) | Action tool calls |
| --- | --- | ---: | ---: | ---: | ---: |
| 09 | 0 | 17 | 34.17 | 84.88 | 6 |
| 09 | 4 | 19 | 27.46 | 106.96 | 4 |
| 10 | 0 | 10 | 51.32 | 97.15 | 5 |
| 10 | 4 | 11 | 48.27 | 112.05 | 4 |
| 11 | 0 | 13 | 45.01 | 81.99 | 6 |
| 11 | 4 | 13 | 41.73 | 66.69 | 6 |

Latest cells each sent 14 requests, completed 13 responses and made 6 action-tool
calls. Completed waits total 585.12 / 542.50 seconds: 95.73% / 88.73% of recorded
611.2 / 611.4 second elapsed times, with 600-second task budgets. Action-tool
calls and low-level controller steps are distinct. Other calls include observation,
memory and geometry. Different candidate versions are not a causal speed comparison.

Remote direct probes (`trust_env=False`, no retries, thinking disabled) using the
existing Flash profile returned three short requests in 1.016, 0.671 and 1.497
seconds. Each asked only for OK, allowed 32 output tokens, and sent 183 bytes.

Reconstructed the last completed request (#13) from each iteration-11 archive
with the installed provider and mock transport. Recorded text, original image
bytes, 18 declarations, tool-choice constraints and 16384-token output budget
were retained. Each contains four images; payloads are 3,680,058 / 3,419,266 bytes.
Independent HTTPX HTTP/1.1 direct replays made three measured attempts (task0
payload twice, task4 once). All failed with WriteTimeout sending the request
body after 90 seconds, without response headers. Totals: 90.337, 90.141, 90.244
seconds. In the final pair TCP/TLS completed in 0.140 / 0.242 seconds. This
establishes upload-stage failure for these probes, not successful API latency
or a decomposition of historical SDK waits. The transport differs from the
experiment SDK. No settings were changed.

The first diagnostic script completed three short probes and one measured upload
timeout, then was interrupted during its second large-payload attempt. That
interrupted attempt has no completed measurement and is separate from the three
recorded timeouts. The later instrumented pass confirmed request reconstruction
completed; no SDK reconstruction bug was established. Original logs remain under
remote `debug/qwen-api-timing-20261110/`. There were six completed diagnostic
measurements plus one interrupted attempt, with no automatic retries.

Response/tool contents were discarded. No robot actions, experiments, proxy/network
changes, or harness/prompt/experience edits occurred. The research loop remains
paused. Credentials stayed in memory; request bodies/images are not in Git.
Validation checked JSON structure, sums against saved metrics, probe counts and
trace stages. No new unit/Sphinx run was needed for standalone measurement/report
changes; no implementation changed.
