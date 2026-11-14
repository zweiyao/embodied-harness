# Object-T final six IPv4 cells

The user prioritized completing LIBERO before the queued RoboDojo/Astra task.
The earlier request to unload LIBERO caused two operator-aborted attempts;
those raw records and their stop reason remain preserved and are excluded.
Previously settled results are unchanged: retain the 40 original IPv4 cells and
four IPv4 replacement cells, then run only the six missing task/seed pairs.
Previously settled task failures are not retried. The older task 8 / seed 1
attempt was already idle after a complete model response before the operator stop;
its record is retained, not retroactively reclassified. Its replacement is a new
attempt under the newly approved settlement policy. This protocol change must
remain visible when interpreting the final table.

Missing pairs: (1,3), (8,1), (8,3), (9,0), (9,2), (9,4).
Two independent workbenches share the restored original LIBERO Pi0.5/SAM3 pool.
Model, 17 native tools, v1 experience, request/token limits, timeout policy and
runtime source remain frozen at revision 5918178. Networking inherits the
separately selected remote IPv4-direct profile. The remote external proxy and
RoboDojo/Astra task remain deferred; Mac networking is unchanged.

The user explicitly approved a batch-only terminal rule: a complete stop response,
idle conversation, paired model/tool calls, no finish call and the latest native
terminated flag false count as model_stopped_without_finish. Write
batch-adjudication.json first, then cancel the idle conversation only to release
resources. Preserve the raw harness outcome (aborted); the derived result records
both that raw status and the approved failure classification. No extra prompt,
observation or robot action is injected. Pending network/tool calls, errors,
incomplete responses and successful environments cannot trigger this rule.

Validation: 15 synthetic boundary checks plus two historical state replays pass;
the 44+6 metadata-only fixture verifies all 50 unique cells and five per task
without touching actual result files. Ruff/pre-commit checks pass for the helper
and generated runner sources. The 460 protected source/material/config hashes
remain unchanged. No harness unit suite is rerun because runtime source is frozen.
Launch counts in launch-summary.json are historical; final results are recorded
in final-summary.json.

prepare_final6.py reuses archived preparers/runners and records the new model-pool
ports without modifying historical scripts. summarize_final50.py runs after all
six valid results settle and writes the final IPv4-only 50-cell table remotely.
Cached input tokens remain a subset of input, not an additional token charge.
Original incomplete cases and infrastructure incidents remain distinct from
valid task failures. Raw observations, videos, credentials and model weights are
not committed.

## Final result

Completed at 2026-11-13 16:59:06 Asia/Shanghai and rechecked on November 14:
50 unique task/seed pairs, five per task, 45 native successes (90%). All six
continuation episodes succeeded. Task 4 succeeded in 3/5 attempts and task 6 in
2/5; every other task succeeded in 5/5. All five failures exhausted the 50-model-
request budget; none was a wall-clock timeout. Controller and both private
workbenches exited successfully, with no remaining cells to resume.

Across all 50 settled episodes, mean model requests were 23.62, mean elapsed time
was 584.56 seconds, and mean input plus output tokens were 767,299.14 (38,364,957
total). These include valid failures. The source summary SHA256 is
`a06d2b58602e6230053155706ce1238ebfa0eef76391d4dbc74310d4e4d60158`.
Remote validation confirmed 50 unique pairs, exactly five per task, 45 successes
and the five budget-exhausted failures. Only this small summary is archived here;
raw run records and videos remain remote. No runtime, network or experiment
configuration changed during this completion check. Unit tests and Sphinx builds
were not repeated for standalone result documentation.
