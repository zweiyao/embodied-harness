# Findings and investigation log

Symptom: three 300-second timeouts, no action in tasks 0/8 and four open-gripper move_to calls in task 4. Frozen source and original workbench are unchanged.

## Iteration 1 — event and loaded-material trace

Read event responses, declared tools, frozen guide/user/index and every actually loaded experience. H1 was eliminated: new entries were delivered, not truncated. H2 survived: old task narratives were selected, including unconditional historical manual-grasp advice. The current user prompt also asks to localize target and destination before performing the task. Neither observation alone proves a causal prompt effect.

## Iteration 2 — numerical replay and minimal reproduction

Run analyze.py remotely with the exact hash-pinned published function on archived frames. All 40 batches/267 points match recorded output. Independent medians match 247 valid points; the other 20 points are explicit per-patch errors from four radius=0 calls. A synthetic fully valid plane reproduces radius=0 failure, while radius=1 succeeds. This positively confirms the schema/implementation mismatch. No runtime source was modified.

## Iteration 3 — image and action-feedback review

Inspect task-4 and task-8 original high-resolution images and compare selected pixels with text and returned geometry. Task 4 conflated a surface point with a feasible grasp approach; the trace itself reports rim straddling after a failed descent. Two descents ended at 0.0317/0.052 m residual after using their action-step limits. Task 8 sampled only the unchanged initial frame, with 12 exact repeated samples among 176; most other queries changed pixels without establishing a grasp decision. Do not call all queries duplicates or claim a specific contact/IK cause.

## Iteration 4 — timing and result-validity audit

Completed model request/response intervals occupy about 95–98% of the configured budget; all tools together take about 8 seconds per episode. Task 4 has a single 97.308-second completed request. Task 8's reported input grows from 5593 to 108879 tokens and batch return text totals 101053 characters. These are context/call-cost observations, not a measured pure-network mechanism.

The previous top-level error counter missed nested per-patch errors. Preserve the original evidence but annotate task 0 as affected by a confirmed experimental-tool defect; it is not a clean task-effectiveness failure. Tasks 4/8 did not trigger that defect. Proposed correction: fix, verify and repeat that cell separately before testing the next candidate.

## Proposed next step

Concrete source/schema changes, candidate-only language edits, full conditional memory draft, and a bounded validation plan are in proposal.md. Nothing in that proposal is deployed. Existing project rules require explicit approval of the new scope. No further model experiment or action was run during this investigation.
