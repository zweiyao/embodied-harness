# Experiment record folders

The shared `/runs` page groups records into expandable environment and task
folders with counts. Task cards load on first expansion and keep their existing
detail URLs, instructions, metrics and video links. Records are newest first
within each task. LIBERO suites remain separate; missing task metadata is kept
in its own folder. Named task numbers follow the current startup catalog and
are displayed alongside stored task names. Each service still lists its own
configured run roots. No files are moved or reclassified on disk.

Remote validation (Python 3.11, existing cached Node.js added to the test PATH):

- Dashboard unit tests: 130 passed.
- Full unit suite: 2162 passed / 11 skipped in 74.96 seconds.
- All-files pre-commit: passed.
- EN/ZH Sphinx builds: `-W --keep-going`, both passed.
- Headless Chrome checks on ports 8094/8083/8092/8093: folder counts match
  APIs (81/12/255/59 records), expand/reopen does not duplicate cards, existing
  details and the return link work, and no page errors occur. Sample RoboDojo
  and LIBERO videos return HTTP 206 for range requests; the sampled Flexiv and
  UniVTAC records have no video. This is not a claim about every historical video.
- Desktop and 390px layouts checked; the expanded mobile RoboDojo task has no
  horizontal overflow. Rendered EN/ZH guide paragraphs retain the `/runs` code
  span without literal RST backticks. Mac access to the RoboDojo page returns 200.

The four frontend files were applied to the three live source roots after
checking original hashes and dry-running the patch. Independent legacy video
rendering is preserved. All six workbench PIDs are unchanged, with no restarts,
experiment launches, robot commands, networking changes or data migrations.

Detailed scripts, screenshots, original backups, deployment hashes and logs
remain outside Git in
`/home/zwy/work/embodied_harness/validation/run-folders-20261116/`.
The desktop browser integration was unavailable; live UI checks used an
isolated remote headless Chrome instance. Screenshots and raw run data are not
committed. This UI validation does not establish task success.

Record cards display the saved `outcome.environment_success` instead of raw
configuration JSON: true is task success, false is task failure, and missing
values are explicitly unknown. `status=completed` alone never implies success.
Complete configuration remains on the detail page.

Follow-up validation: 131 dashboard tests; full suite 2163 passed / 11 skipped
in 73.07 seconds; all-files and explicit new-file pre-commit checks pass.
Four live workbench browser checks verify displayed card results against each
sampled saved outcome, absence of raw tool/budget JSON, unchanged detail and
video access, and mobile layout. The three-file patch preserves all six process
PIDs. Follow-up evidence and screenshots are under `result-card/` in the remote
validation directory.

## Permanent record deletion

Record cards and details include a permanent-delete button. Its confirmation
shows the run ID and remote directory. `DELETE /api/runs/{id}` also requires
the matching `confirm_run_id`. Only a catalogued task directory beneath a
configured run/history root is eligible. Active Session runs are refused; a
saved outcome and, when present, a final `run_end` journal event are required.
Legacy records without an outcome remain undeletable until their archive state
is resolved. Nested external symlink targets, sibling records and parent
directories are preserved. Deletion does not modify tools, memories or scoring.

Validation: 139 dashboard tests; full suite 2171 passed / 11 skipped in
72.66 seconds; all-files and explicit UI-test pre-commit checks pass. EN/ZH
Sphinx warning-as-error builds pass. Live browser tests on all four workbenches
verify cancellation, confirmation, unfinished-record refusal, permanent removal,
404 detail/artifact links, count refresh and mobile layout. Only four clearly
labelled disposable fixture records were deleted. All 407 original IDs and
1200 existing configuration/outcome/manifest hashes remain unchanged; ten legacy
missing outcomes remain absent. No experiment was launched.

Six idle workbench backends were reloaded after confirming no pending tasks,
Flexiv unarmed/no lease/IDLE, and preserving model/tool/budget selections. Two
auxiliary transient units were collected on stop and recreated with the original
launcher; its shared-model addresses now refer to the reloaded owner. RDK, RGB-D,
ENV and both access-service PIDs are unchanged. LIBERO's configured borrowed
VLA/SAM3 ports are not listening: its record management works, while experiment
initialization waits for those dependencies. No additional LIBERO weights were
loaded. This remains an explicit deployment limitation.

Evidence under the remote `delete/` directory retains before/after metadata
hashes, deployment/recovery scripts and logs, unit/docs logs, UI checks and
screenshots. Only small validation summaries are committed.
