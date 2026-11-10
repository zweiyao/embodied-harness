# Iteration 09: calibrated-view screen

R18+W2+F+V scored **0% (0/2)** on task0/4 seed0. Both reached the full
600-second planner limit; finalization adds about11 seconds to reported outcome
time. Both remain valid failures. V is not promoted for success. C remains the
historical two-cell reference, not an estimate of ten-task capability.

| Task | Official success | Requests / completed | Tool calls / actions | Calls before action | First action |
| --- | --- | --- | --- | --- | --- |
| 0 | false | 18 / 17 | 17 / 6 | 10 | 228.029s |
| 4 | false | 20 / 19 | 19 / 4 | 13 | 213.346s |

## Earliest observed deviations

Task0 sampled six coordinates at step0 before a language-only Pi0 pickup that
consumes none of those coordinates. Pi0 exhausted24 chunks and reported its
pickup heuristic false. External frames01/03/05/06 show the cream-cheese box
remaining on the table while the neighboring milk carton tips during subsequent
manual descent. Two translate_to calls stop with residual distances0.0761m and
0.0777m despite80 control steps each. Closing then lifting does not lift the
cheese. This is evidence of ineffective, contact-interfered recovery, not proof
of an arithmetic transform error. The exact contacts cannot be identified from
these external frames alone. Repeating downward targets without resolving the
obstruction is the observed decision failure. Neutral gripper command0 in
translate_to retains the actuator target; it must not be described as reopening.
Neither basket delivery nor the second object was attempted.

Task4 made thirteen calls before pickup, including all three experience bodies,
five separate backprojections and an overlapping batch query. These queries are
not inputs to the ensuing Pi0 call. The yellow/white mug was then transported,
previewed, aligned and released. Frames02/03/04 place it at the image-left plate;
the release frame alone does not establish stable support or an official partial
goal predicate. The other requested mug remains on the table. No second-object
pickup occurs before timeout. P was actually adopted here, but neither adoption
nor apparent partial progress is a task-success result.

The seven reviewed640px JPEGs were derived only for analysis; no policy image,
original observation or recording was modified. Their paths/hashes are recorded
in visual-review-provenance.json. Raw images remain outside Git. Full task paths
in cost-summary.json identify episodes; run_id alone is not unique across roots.

## Interpretation and limits

Both episodes spent more than3.5 minutes before the first action. The W2 soft
next-action instruction and its on-demand experience did not prevent geometry
work that was unnecessary for that immediate action. This motivates testing an
explicit phase boundary; it does not prove geometry can be omitted for manual
recovery or placement. Failed grasp/contact recovery is a separate unresolved
mechanism. Do not claim one phase change solves both.

Completed model waits total1102.484s over36 responses (mean30.625s). These are
end-to-end waits, not isolated network or inference time. Later requests include
accumulated image history; that correlation does not identify its causal effect.
No proxy, network, image encoding or history-pruning change was made. Mac network
and background forwarding were not changed during this iteration.

## Validity, preservation and costs

All10848 protected files, runtime child coverage, actual18 schemas, frozen
materials/configuration, image byte/frame bindings and owned cleanup passed.
Both second actual model requests contained exactly the calibrated external and
wrist images. F was active in38 requests; all36 completed responses carried tools,
with no pure-text retry or finish call. Both lanes and batch are inactive with
MainPID0/exit0. No runtime incident or policy replacement occurred.

The initial preflight catalog-metadata construction error preceded any task or
model request. Original evidence remains in preflight-01; the repaired setup
uses the same shared catalog as the launcher and retains strict comparison.
This preparation error is not an excluded policy attempt.

Costs:38 requests,508599 input tokens including433664 cached,2204 output tokens,
1222.5 summed outcome seconds; two connectivity checks are separate. The01–09
ledger totals22 valid development attempts and386 requests. Distinct conditions
must not be pooled into a success rate. Timing/lane differences confound the
historical comparison to08; no independent50+50 evaluation has started.
