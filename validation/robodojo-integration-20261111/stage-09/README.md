# RoboDojo native budget and gripper feedback repair

The approved two production-file changes are implemented in the isolated runtime. Native RPC now rejects an action before dispatch when the current count reaches min(max_episode_steps, official task step_lim), in dev and eval-fair. Status, action info and development diagnostics expose that effective cap; the official native task limit and success predicate are unchanged.

set_gripper still submits exactly one native action. Its gripper field now says close_commanded/open_commanded, with separate target_opening and measured_opening (normalized 1=open, 0=closed). Missing measured feedback is null. No wait loop, repeated action, new completion tolerance or controller change was introduced. The partial close observed at about 0.65248 is now reported truthfully; this repair does not make it a completed close.

Seven new regressions produced 6 failures / 1 pass against the old code. After repair: 172 RoboDojo tests passed; full Python 3.11 unit tests passed 2050 / skipped 15 in 72.47 s; pre-commit passed. Existing diagnostic-permission fixture state and one approved tool-description snapshot were updated to the new contract without removing schema, permission or full-comparison assertions. Intermediate failures remain in remote logs and summary.json.

Real simulator validation used the approved profile and fixed bottles task/layout 0, with three environments run serially:

| Check | Result |
| --- | --- |
| Original eight-call movement/gripper diagnostic | Passed; 8 native actions; all state records returned three images |
| Gripper feedback | Both arms returned explicit command, target, measured opening and effective cap 96 |
| dev cap 2 | Two current-state hold targets accepted; third rejected; counter stayed 2; diagnostics agreed |
| eval-fair cap 2 | Two hold targets accepted; third rejected; counter stayed 2 |
| Cleanup | All three owned environments exited 0 before fallback; nine videos decoded; no new GPU process remained |

The 608 original protected files and existing collector/workbench services remained unchanged. No physical hardware action, planner request or VLA request ran. Raw observations, videos, predictions and logs remain outside Git.

This is bounded integration evidence. Full gripper closing, independent geometry, cross-task coverage, VLA action execution, CLI policy chain, GPU runner and unified workbench are not certified by this check. Previously documented dependency metadata conflicts remain.
