# RoboDojo tasks 1–10 with a longer planner budget

The operator authorized one fresh rollout for each dashboard task index 1–10,
with a 1,800-second planner budget instead of 600 seconds. Indices use the
existing zero-based inventory; task 0 is not included. Layout is 0 throughout.

The execution source is `569fc71`. Astra/high, explicit native analysis/full
access, indexed v1 experience, 120 model responses and the eight selected EEF
tools remain unchanged. Pi is not selected. Native actions remain unlimited in
this development diagnostic; results are not an official-budget benchmark.

Three isolated workbenches share the existing VLA/SAM3 processes and retain
separate episode contexts, ENV processes and recordings. Historical capacity
checks validated three simultaneous environments, three-camera observations and
dual-arm IK; four environments were not validated. The batch serializes ENV
initialization, requires 11 GiB of free GPU memory before initialization, and
stops new dispatch if free memory falls below 3 GiB.

| Dashboard index | Task | Lane |
| --- | --- | --- |
| 1 | arrange_largest_number | A |
| 2 | arrange_largest_number_random | B |
| 3 | build_tower | C |
| 4 | classify_objects | A |
| 5 | classify_objects_by_language | B |
| 6 | cover_blocks | C |
| 7 | deposit_coin | A |
| 8 | fasten_screws | B |
| 9 | fill_egg_holder | C |
| 10 | fill_pen_holder | A |

A timeout is a valid failure even when the final native success flag is true.
Infrastructure incidents are excluded and stop further dispatch for inspection.
The queue never resubmits a launched episode, and original outcomes remain
unchanged. No new task-specific guidance, experience or action logic is added.

Remote operational evidence and live results are under
`/home/zwy/work/embodied_harness/validation/robodojo-tasks1-10-1800-20261116/`:
`plan.json`, `lane-checks.json`, `launch-NN.json`, `current-A/B/C.json`,
`results.json` and `summary.json`. The public records page is
<http://10.162.250.228:8094/runs> and includes all three lanes.

Only the public launcher's planner timeout and the next-task configuration were
changed for lane A; its running service was not restarted. The prior launcher is
retained privately. Lanes B/C use loopback-only ports 18094/28094 and the same
planner configuration. Network selection and Mac networking are unchanged.

Validation includes remote Python compilation, shell syntax checking, exact
configuration equality across the three lanes, live Astra/high connection
checks, and the launch/resource snapshot in `launch-summary.json`. The harness
source is unchanged; existing source verification remains separate from these
operational checks. The snapshot records startup evidence, not final task
success rates. Recordings, raw observations and private workbench configuration
are not committed.
