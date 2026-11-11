# Iteration 07 terminal diagnosis

All four cells reached the configured 600 s planner limit with official
`environment_success=false`. Parent R18 and R18+W2 each achieved **0/2 (0%)**.
The failures remain valid results; this screen establishes no improvement.

| Arm | Task | Requests / completed responses | Tool calls | Completed action calls |
| --- | --- | --- | --- | --- |
| R18-reference, lane a | 4 | 10 / 9 | 14 | 2 |
| R18-reference, lane a | 0 | 9 / 8 | 11 | 3 |
| R18+W2, lane b | 4 | 16 / 15 | 15 | 1 |
| R18+W2, lane b | 0 | 2 / 2 | 3 | 0 |

For task 4, the parent grouped the three startup checks in response 1; W2
split them across responses 1–3 despite saying it would read them together.
W2 then serially read all three experience bodies, listed memory, and made
repeated back-projection requests. Its first action followed 14 tool calls;
the parent's first action followed 12. This cell directly contradicts an
assumption that the added wording necessarily produces startup batching or
reduces pre-action detours.

The parent's task-4 response 8 explicitly called the yellow/white mug the
“right plate target,” contradicting the recorded task's left-plate relation.
This error preceded any placement calculation. Its Pi0 pick exhausted 24
chunks with no post-descent lift; the inspected external step-1 image shows
the mug at its original table-level region beneath the fingers. Response 9
then closed the gripper. That call changed finger position but did not test
transport: EEF height remained approximately 0.510 m. No stable grasp or
placement was established before timeout.

W2 task 4 eventually stated the correct two mug/plate relations in response
15, selected the plain white mug and dispatched Pi0. The native heuristic
reported success with 0.0869 m post-descent EEF ascent and a small final finger
opening. This review did not inspect that grasp's images or an independent
transport check, so it does not equate the heuristic with verified holding.
No placement action followed before timeout. The NEXT text also included a
function-call expression rather than the requested bare action name.

Parent task 0 first exhausted a cream-cheese pick with zero ascent and an
approximately 0.0799 m opening. Two later `translate_to` calls reached reported
position errors of 0.0098 m and 0.0116 m while retaining gripper command 0;
the recorded EEF positions confirm robot motion, and the measured opening
remained approximately 0.0798 m. These are geometric-motion observations,
not evidence that the cheese moved with the hand. No task-0 image comparison
was performed in this review; object motion, collision and holding are not
inferred from these proprioceptive values.

W2 task 0 returned the three startup tools, then response 2 contained only
`NEXT=pi0_pick(prompt="pick up the cream cheese box"); NEED=none` as text.
There was no tool-call part or actual pick dispatch. No further model request
or action was recorded before timeout. Thus a written action intention did
not become execution. The separately reviewed API-loop completion behavior
and dashboard wait explain why this case requires an output-contract fix;
changing grasp geometry cannot address an action that was never dispatched.

Neither arm invoked R or P in these four cells. The main observed failures
were pre-action detours, a task-relation mistake, unsuccessful/unverified
grasp progression, and text-only action declaration. They do not show a
rotation-controller or placement-coordinate arithmetic failure. W2 is a
soft instruction and did not reliably enforce its proposed workflow. Fixed
lanes, temporal ordering and only two tasks limit causal interpretation.

Evidence root:
`/home/zwy/work/embodied_harness/experiments/qwen-continuous-20261109/iteration-07`.
Each lane has `runs/session/tasks/0001_libero_10_task_t4_s0` and
`runs/session/tasks/0002_libero_10_task_t0_s0`, containing the cited
`events.jsonl` and `outcome.json`. The inspected parent task-4 image is
`a/runs/session/tasks/0001_libero_10_task_t4_s0/agentview_high.png/01.png`.
Full task paths identify cells; run IDs repeat across isolated roots.
Final validity, observer cleanup and the retained audit metadata correction
are documented by the run owner's finalized verification artifacts.
