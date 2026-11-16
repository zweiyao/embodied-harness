# RoboDojo task 0: controller incident

One operator-requested `align_blocks`, layout 0 episode ran from revision
`290884c` with Astra/high, full native access, the indexed v1 experience corpus,
and eight EEF-mode tools. The native instruction was: use the set square to push
three blocks into a straight row, then return the robot arm. Limits remained
120 model responses and 600 planner seconds; no harness or network settings
changed during the episode.

Run `1e81ae7f7eb07fc139d8` ended after 202.0 seconds, including 159.5 planner
seconds, with 19 responses, 11 EEF requests and 666,636 input-plus-output tokens.
No Pi or other robot action tool was called. The environment reported false and
the model finished `stuck`; the time budget was not exhausted.

**This is excluded from model success-rate statistics as a controller incident.**
The last request passed decision-limit validation before entering the server
loop. Its target was within the recorded pre-state limits (0.03951 m and
0.33800 rad), but the post-error state put its rotation error at 0.35391 rad,
beyond the 0.35 rad gate. The internal `env.step_eef` validation raised an RPC
error. The measured arm pose changed and the multi-step call's executed prefix
was not returned. Ten prior calls contain 50 contiguous native ACKs; the final
call's actual native-step count is unknown. The model stopped under the
uncertain-execution rule, saved its audit and did not reset or replay the action.

`incident-audit.json` records a no-motion replay of the validator using the saved
pre/post states. It does not establish an exact count for the unreported steps.
The controller's decision-limit/partial-feedback contract needs investigation
before a valid repeat; no control protection or limit was changed here.

The external collector initially classified the episode from top-level error
and environment verdict alone. `task-result.initial.json` retains that original
classification remotely; the audited summary excludes it after inspecting the
nested tool error. Original `outcome.json`, `result.json`, observations, and
videos are unchanged. The web page retains those original native/model results.

[Episode record](http://10.162.250.228:8094/runs?id=1e81ae7f7eb07fc139d8) ·
[Head-camera video](http://10.162.250.228:8094/api/runs/1e81ae7f7eb07fc139d8/artifact/videos/episode_2026-11-16_10-08-36_cam_head.mp4)

All three videos decoded 128 frames at 25 fps; the head video supports HTTP 206.
Source and memory-index hashes matched before and after. Full evidence remains
under `/home/zwy/work/embodied_harness/validation/robodojo-layered-task0-20261116/`;
only the small summaries are committed. No task performance improvement is claimed.
