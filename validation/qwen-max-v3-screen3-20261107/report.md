# Qwen Max with thinking: three-task execution record

All 27 recorded requests selected qwen3.8-max and enable_thinking=true. All 24 completed responses identified that model and contained nonempty thinking parts. This is a provider reasoning switch, not merely a display option. The existing adapter maps reasoning_effort=medium to this boolean switch; no separate graded provider intensity is claimed.

All three task attempts reached the full 600-second budget and have official success=false. No tool-error response or runtime infrastructure error was recorded. Initial-scene comparison found a stove-placement difference in task 8; its outcome is retained as an execution record and **excluded from the matched-initial-scene comparison**. Only tasks 0 and 4 are included in that comparison: Max 0/2 (0%), Flash 0/2 (0%). Do not report this as a clean three-cell paired effectiveness experiment.

| Task | Status | Requests | Actions | Pre-first-action tool calls | Mean returned-request wait s | Reported reasoning tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 600 s timeout | 11 | 6 | 6 | 50.7 | 12,381 |
| 4 | 600 s timeout | 9 | 3 | 4 | 71.1 | 18,329 |
| 8 (excluded from paired comparison) | 600 s timeout | 7 | 3 | 7 | 82.1 | 18,558 |

Recorded elapsed times including finalization are 610.3, 610.5 and 608.6 seconds for tasks 0, 4 and 8. Each ends with one unfinished model request; returned-request averages and reported token counts omit that unfinished request. Request/response time includes transmission, provider processing and reception and is not pure network latency.

## Interpretation and limits

- On the two included tasks, pre-action tool calls were Flash 5/22 versus Max 6/4. Their conditional mean is 13.5 versus 5.0 (n=2 per condition). This reduction did not produce success and does not establish faster completion.
- Task 0 called release once but the task requires two objects and remained unsuccessful. Task 4 had no release. This batch does not validate the effectiveness of the optimized harness.
- The batch helper was not selected for an actual call in any Max run. The container helper ran three times: two inconsistent-rim results in task 0 and one measured result in task 4. Availability and valid execution are separate from adoption and task gains.
- Max successfully read object-relative-transfer and next-action-evidence in task 0; tasks 4/8 read next-action-evidence. No successful grasp-feature-evidence body read was recorded in this batch.
- The same tasks, configured seeds, prompts, memory package, tool versions and budgets were reused, but both model and thinking mode changed. No causal model-only or thinking-only claim is supported.

## Initial-scene caveat

Initial high-resolution agentview PNG files for tasks 0 and 4 are byte-identical between Flash and Max. Task 8 differs at decoded pixels, localized to the stove: 4.56% of pixels differ, mean absolute channel difference 1.227/255. The initial robot pose/gripper state and task instruction match. This is not PNG encoding alone. The environment-level cause is not confirmed; no environment code or reset behavior was modified, and no extra trial was launched. See [initial-scene audit](initial-scene-parity.json) and [comparison scope](comparison.json).

## Validation and preservation

Only the isolated Max profile/startup arguments changed. All 798 protected source, material and library files remained unchanged. Preflight passed three actual memory reads, three denied writes, five outcome-classification checks, two published-tool Docker checks and two model/config connectivity checks. Four existing serialized-body cases plus one exact Max/medium case passed. Actual request settings and provider thinking parts were audited separately.

Startup scripts clear all six proxy variables after activation; the batch unit also clears them via UnsetEnvironment. Live inspection found none in nine related processes. Original workbench identity/config/network remained unchanged. Both owned environments were stopped after completion. Full unit/pre-commit suites were not repeated for this external model/config-only run; prior unchanged-core validation is 2009 passed / 15 skipped, with documented pre-existing full-pre-commit findings. Scoped Ruff and final JSON/link checks apply to this record.

See [execution audit](final-verification.json), [thinking audit](final-thinking-audit.json), [cleanup](cleanup.json), [video verification](video-verification.json), and [authorized scope](scope.md). Raw observations, videos, credentials and thought text are not committed. Full records remain under `/home/zwy/work/embodied_harness/experiments/qwen-max-v3-screen3-20261107`.
