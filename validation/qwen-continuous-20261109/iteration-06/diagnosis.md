# Iteration 06 trajectory diagnosis

Both frozen R screens ended on the configured 600 s planner budget on
2026-11-10 at 07:25:07 UTC: **0/2 success (0%)**. These are valid budget
failures, not unexpected incidents. Neither episode called `rotate_axis`,
so this screen does not establish a task benefit or a task failure of R.

| Cell | Requests / completed responses | Tool calls / action calls | R / preview / align | Last completed step |
| --- | --- | --- | --- | --- |
| Task 4, seed 0, lane a | 9 / 8 | 11 / 2 | 0 / 1 / 0 | 2 |
| Task 0, seed 0, lane b | 8 / 7 | 10 / 2 | 0 / 0 / 0 | 2 |

The run owner reports final source/runtime verification and cleanup passed;
see `results.json`, `final-verification.json`, and `cleanup.json`. This review
used recorded tool requests/results and full-resolution external/wrist images
only. It made no simulator actions, model calls, or runtime/configuration edits.

## Task 4: a stage decision precedes the incorrect placement inputs

1. Request 6 called `pi0_pick` for the yellow/white mug. It stopped after 19
   chunks with its native heuristic `success=true`, EEF post-descent ascent
   0.0803 m and final finger opening 0.0107 m. External step 0→1 shows the
   target mug moved upward with the hand; wrist step 1 shows its rim between
   the fingers. This is evidence consistent with a grasp, not an independent
   stable-holding test.
2. Request 7 repeated the same pick rather than validating the existing grasp
   or starting target-directed transport. The model changed the pick thresholds
   to lift 0.03 m, descent 0.05 m and minimum opening 0.02 m, with eight chunks.
   The opening lower bound now excludes the preceding 0.0107 m opening. The
   native implementation starts a new descent/ascent detector and executes a
   learned action chunk before checking it; this call is not a passive grasp
   check. It returned `success=false` and opening 0.0768 m. External/wrist
   step 2 show the yellow mug over the image-right plate, whereas the task
   requires it on the left plate. The images do not independently establish
   that it was released or stably supported; zero explicit `release` calls
   must not be interpreted as zero gripper changes inside Pi0.
3. Request 8 called `preview_placement` at step 2. Its actual returned overlay
   places O on the mug's visible inner wall near the rim, all four P marks and
   C on bare table, and most of R around table rather than the left plate's
   visible interior. R0 is at/near the plate's outer rim. An independent visual
   reviewer confirmed these point roles. Thus the wrong target surface was
   selected **before** depth projection or offset arithmetic.
4. P fit the selected horizontal table plane (residual 0), preserved the
   selected-feature offset, and returned `requires_waypoint` for a 0.4504 m
   correction. It issued no executable ID; `align_placement` was never called.
   The distance guard prevented this proposed direct move, but did not detect
   the semantic mistake. `semantic_status=caller_selected_not_verified` was
   correct. A planar region and C inside R establish geometric consistency
   only, not target identity, holding, or footprint clearance.

The earliest observed questionable decision is the repeated active pick after
evidence consistent with an attained grasp. The later target-role error is
directly visible. There is no model explanation establishing why it repeated
the pick or chose those pixels, so a specific internal rationale, systematic
pixel scaling error, or stable-grasp destruction is not claimed. The evidence
supports investigating explicit grasp-stage validation and semantic checking
of selected image roles; it does not support changing P geometry tolerances.

## Task 0: failed grasp, then geometric arrival without clearance evidence

Request 5 exhausted 24 Pi0 chunks with `success=false`, zero post-descent
ascent and final finger opening 0.0797 m. External step 1 shows the cheese
still at table level beneath/near the hand and adjacent milk carton. The
failure occurred before any R or P opportunity; the final pose alone cannot
identify which learned-controller decisions caused the failure.

Request 6 sampled three nearby visible surface patches. One patch includes
dark edge/robot pixels, so these samples cannot by themselves define a
collision-free grasp pose. Request 7 used `translate_to` toward
`[0.104, -0.167, 0.52]`. The primitive reached a reported 0.0094 m position
error in 11 reported steps while retaining gripper command 0. External
step 1→2 shows the milk carton tipped and the cheese remaining on the table;
the final opening stayed approximately 0.0797 m. Geometric target arrival
and retained gripper target therefore did not establish a grasp or a clear
motion path. The images support a nearby-object interaction during this
motion, but do not isolate its detailed contact dynamics. No evidence here
shows a coordinate arithmetic error in M.

## Budget and interpretation

Completed model waits totaled 470.629 s / 8 responses (58.829 s average) for
task 4 and 453.072 s / 7 (64.725 s average) for task 0. The final canceled
request in each episode is excluded from those averages. Each episode had
only two completed action calls before timeout; neither called `finish`.
These are event timings, not a network diagnosis or an estimate of model
compute time. Long waits restricted recovery opportunities, but do not erase
the observed stage-selection and target-role errors.

R's bounded robot-only transform probe remains separate mechanism evidence.
This screen supplies no R adoption evidence, no held-object rotation evidence,
and no success-rate improvement. P was adopted once but never committed; its
output made a semantic selection failure inspectable. Neither result justifies
promoting the candidate over the incumbent.

## Evidence locations

Remote experiment root:
`/home/zwy/work/embodied_harness/experiments/qwen-continuous-20261109/iteration-06`.
The task directories below each contain `events.jsonl`, `outcome.json`, and
per-step `agentview_high.png/00.png` etc. and `wrist_high.png/01.png` etc.:

- `a/runs/session/tasks/0001_libero_10_task_t4_s0`
- `b/runs/session/tasks/0001_libero_10_task_t0_s0`

Actual task-4 request-8 overlay, under its task directory:
`inputs/19a9b8aa3ebc77109ec859d093ea12d8b16e9e8ce6da6b1167c85ce8a8def5fd.bin`.
Raw observations and videos remain outside Git. Native pick semantics were
checked against the frozen `robots/libero/tools.py:206` implementation; no
production source changed during this diagnosis.
