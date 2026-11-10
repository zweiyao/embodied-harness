# Iteration 08: explicit-finish screen

R18+W2+F achieved **0/2 (0%)** on task0/4 seed0. Both reached the full
600-second planner limit and remain valid failures. The observed outcome
elapsed times include finalization beyond the planner budget. F is not promoted
for success; C remains the historical small-screen reference (1/2).

| Task | Official success | Requests / completed responses | Tool calls / actions | Calls before first action | First action from first event |
| --- | --- | --- | --- | --- | --- |
| 0 | false | 6 / 5 | 7 / 0 | not applicable | none |
| 4 | false | 6 / 5 | 10 / 1 | 7 | 301.583 s |

Both grouped view, guide and memory-index reads in their first response. All ten
completed responses contained tool calls. Actual requests used
`allow_text_output=false`; no pure-text output retry or finish call occurred.
The constraint was active, but these attempts do not test recovery from the
specific pure-text stall seen in07. Offline SDK tests remain separate evidence.

Task0 sequentially segmented the basket, cream cheese and a `bottle of tomato
ketchup`, then read the handle-grasp experience. The task actually asks for
cream cheese and **tomato sauce**, and the observed object-name list contains
both `ketchup_1` and `tomato_sauce_1`. Substituting those identities occurred
before coordinate arithmetic or motion. The detector's `found=true` and score
0.93 confirm a match to the supplied query, not that the query matches the goal.
No grasp was attempted. The handle-specific experience was read although the
current task concerns packages and a basket. Without model reasoning text,
the internal cause of that selection is unknown.

Task4 read two experience bodies, segmented both mugs together, then called
Pi0 on the yellow/white mug. The native heuristic reported success after12
chunks, based on0.0836m post-descent ascent and a small finger opening. This is
not independent evidence of stable holding. The next response requested a
`white plate with red stripes on the left side of table` segmentation and
camera metadata, with no transfer, placement-preview, alignment or release.
No placement coordinate was executed, so this run cannot demonstrate a
placement arithmetic error. Image inspection was not completed in this report;
no claim of correct plate identity or stable grasp is made.

Completed model-request waits sum1113.329s across ten responses (mean111.333s).
Those are end-to-end waits, not measured network-only or inference-only time.
The differing scene/tool outputs and request count prevent attributing these
waits to a single cause. Per user direction, no network diagnostic or setting
change was performed. Low request throughput makes unnecessary sequential
checks costly, but batching alone does not verify semantic correctness.

Both runtime child audits, frozen materials/schema, initial-state pairing and
8943 protected files passed. Owned lane and batch units are inactive with
MainPID0 and exit0; original workbench/config/network checks passed. No incident
or replacement attempt occurred. See results.json, final-verification.json,
cleanup.json, closure.json and first-request-audit.json. Full task directories,
not run_id alone, identify attempts. Comparison with07 W2 is historical and
confounded by timing and environment allocation; this is not held-out evidence.

Cost:12 requests,104744 input tokens including64256 cached,1021 output tokens,
1222.3 summed outcome seconds. Two connectivity requests are accounted separately.
Cumulative01–08 cost is20 valid development attempts and348 model requests;
different versions must not be pooled into a success-rate claim.

The reporting-only summarize.py was scoped in postrun-plan.md before creation,
refuses incomplete/unaudited runs and passed remote Ruff/compile checks. Its
ledger delta was checked against the exact results hash and all20 unique task
paths. No policy test was rerun for reporting. Next investigate the explicit
image/frame ambiguity already established by the historical visual audit;
semantic query substitution and action selection remain separate hypotheses.
