# Task 0 repeat: range recovery verified, episode timed out

One new `align_blocks`, layout 0 episode used `6ead00e`, Astra/high, full native
access, eight EEF tools, the existing indexed experience corpus and unchanged
120-response / 600-second planner limits. The old incident episode is retained
and excluded separately.

The range-recovery mechanism worked in the real episode: observation 4 reported
zero executed steps, five cancelled steps and three feedback images. The next
model call used observation 4, changed its target and executed five controls.
The episode continued to 41 EEF requests, with 40 complete calls and exactly
200 contiguous native ACKs. No EEF RPC/physics error occurred. This episode
exercised an entry rejection; mid-chunk partial-prefix recovery is covered by
regression tests and was not triggered here.

**The episode counts as a timeout failure under the operator's rule.** The
final native environment signal was true, but the planner hit its 600-second
limit without `finish`. The first time the native goal became true is not
recorded: agent-side state snapshots intentionally do not expose that score.
Do not infer an on-time task success from the finalization verdict.

Metrics: 52 model responses, 41 EEF requests, 200 confirmed native controls,
600.2 planner seconds, 643.0 total seconds including initialization/finalization,
and 3,149,779 input-plus-output tokens. Pi and other action-tool requests were
zero. Source and memory-index hashes stayed unchanged.

The collector's initial environment-only success classification is preserved
remotely as `task-result.initial.json`; the audited summary applies timeout
precedence. Original `outcome.json` and `result.json` are unchanged. All three
videos decoded 483 frames at 25 fps. No second repeat or time-limit change was
made; this single episode does not establish a success-rate improvement.

[Record](http://10.162.250.228:8094/runs?id=736e5786c205b1a9d2e8) ·
[Head video](http://10.162.250.228:8094/api/runs/736e5786c205b1a9d2e8/artifact/videos/episode_2026-11-16_10-48-47_cam_head.mp4)
