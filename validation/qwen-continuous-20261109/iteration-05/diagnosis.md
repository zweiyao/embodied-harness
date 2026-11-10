# Iteration 05: timeout before placement-tool use

Read-only review of the completed task 4/a (`9cbe14f94f25bc734075`) and task 0/b (`4aeed560761dad4f7217`) episodes. Both are valid 600-second budget failures; neither is replaced or excluded. Official success is 0/2. Each issued nine model requests and received eight completed responses. `preview_placement` and `align_placement` were never called, so this screen does not measure their semantic selection, stale-reference handling, alignment performance, or task benefit.

## Time and earliest limiting stage

The direct source is each run's `events.jsonl` and `outcome.json` under remote `experiments/qwen-continuous-20261109/iteration-05/{a,b}/runs/session/tasks/`. No tool call remained pending during the long waits inspected live; the pending operation was the model request.

| Lane | First action after episode start | Completed model waits: total / median | Sum of tool wall times | Actions |
| --- | ---: | ---: | ---: | ---: |
| a / task 4 | approximately 353 s | 596.22 s / 70.05 s | 3.23 s | 1 |
| b / task 0 | approximately 488 s | 549.34 s / 75.20 s | 6.99 s | 2 |

The final canceled model request is excluded from the completed-wait statistics. Tool wall-time sums can overlap for parallel readonly calls. Recorded episode elapsed times are 610.5/610.2 seconds and include setup around the 600-second planner budget.

The earliest observed bottleneck is repeated slow model requests after image evidence enters the conversation, amplified by additional model-selected experience reads and measurements before the first grasp. The initial text-only responses took about 3–4 seconds; later completed responses reached 40–127 seconds. This temporal association alone does not isolate upload, provider queue, or generation time. The contemporaneous [passive socket snapshot](passive-latency-snapshot.json) independently records IPv6 HTTPS upload queues, retransmissions, and low congestion windows for the owned workbench processes, supporting a transport contribution. Its serialized event sizes contain artifact references and are not HTTP request-body byte counts. A separate transport diagnostic is needed for attribution; these episodes remain timeout failures.

## Task 4: grasp evidence was not converted into the proposed check

Request 6 called `pi0_pick("pick up the yellow and white mug", max_chunks=24)`. The primitive stopped after 11 chunks and returned its lift/closure heuristic as true. The external step-0/step-1 images show the intended mug displaced upward; step-1 wrist imagery shows fingers straddling its rim. Together these support a grasp more strongly than the heuristic alone, but no subsequent carry or additional lift was executed.

Request 7 interpreted the external view as the mug still resting on the table and reread the unchanged step 1. Request 8 again described conflicting views and proposed a small lift to test hand-relative motion, but actually called `sensor_patch_batch`. Its first point, pixel `[639,716]`, is on table immediately below the raised mug; the result reports a table surface. The model never received another completed response to interpret this measurement or execute the proposed lift. This is a concrete evidence/action mismatch, but neither the bad sample nor a placement correction was used in a later action.

The earlier white-mug region measurement also covers mostly table in the initial image. It was not used to command the first learned grasp and must not be presented as the cause of this episode's timeout.

Image references within lane a's task directory: `agentview_high.png/00.png`, `agentview_high.png/01.png`, `wrist_high.png/01.png`. Raw images were inspected in `/tmp`, not added to Git.

## Task 0: first grasp failed; recovery ended before verification

The initial point and segmentation select the visible cream-cheese package; a separate segmentation selects the tomato-sauce can. Request 7 finally calls the cream-cheese learned pick with the ordinary 24-chunk budget and unchanged thresholds. It exhausts the chunks with no closure or post-descent lift. The step-1 external image shows the open hand beside/over the package on the table. This is failure to establish holding, not a demonstrated placement-coordinate error.

Request 8 calls `translate_to` at approximately the existing low height. The ordinary servo reaches its reported positional tolerance, preserves the open gripper target, and records step 2. The package shifts left in the external image while the fingers remain open; the wrist view does not establish a held object. This is consistent with contact during the low lateral motion, not verified held transport. There is no later close/lift check, tomato pick, basket alignment, or release before timeout. The trace does not expose enough subsequent intent to label the unfinished translation alone as a completed recovery strategy.

Image references within lane b's task directory: `segment_overlay_00.png/00.png`, `agentview_high.png/01.png`, `agentview_high.png/02.png`, `wrist_high.png/02.png`. No hidden object poses were used.

## Review boundary

No P argument, geometry, execution, or stale-ID error occurred because P was unused. Some old native-tool arguments were emitted as numeric/array strings and normalized by the existing API argument handling before successful dispatch; these were not implementation failures. This review changed no policy, prompts, tools, runtime configuration, or episode behavior. Source review and prior interface tests establish implementation checks only; this screen establishes no success-rate improvement.
