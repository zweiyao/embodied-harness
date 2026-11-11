# Experiment history and task instructions

The main LIBERO workbench scanned only `research-runs`, while the continuous
study used 22 isolated lane roots. Added server-owned, read-only `history_roots`
and configured those roots. Existing run IDs remain valid; resolved directories
are deduplicated. Artifact access retains its containment checks. No run data was
copied or edited, and no planner, tool, prompt, experience, or run budget changed.

Lists and details display the first nonempty recorded
`states.json: steps[].extras.task_language` as “任务指令（instruct）”. Missing
historical values display “未记录”; task numbers are not used to reconstruct text.

Verified on the remote host: 169 → 195 records; all 26 added records have
instructions. All added detail endpoints resolve. Both iteration-11 videos match
their original SHA256 bytes. Original links and all checked record files
remain unchanged. The idle LIBERO web service was restarted; no task was launched.
Mac direct LAN API verification returned 195 records without changing networking.

Validation: 31 focused tests; complete unit suite 2193 passed / 15 skipped;
5 tests against deployed source; scoped pre-commit passed. Full pre-commit failed
on pre-existing validation scripts (274 remaining diagnostics; 18 modified files
in the isolated checkout, restored afterward). Browser visual inspection was
unavailable because the browser access host could not be reached. CI's full
Python matrix was not run.

Iteration 11 finished at 2026-11-10 20:24:18 Asia/Shanghai: task 0 and task 4
both exhausted 600 seconds, official success false (0/2, 0%). The original
outcomes, videos and cleanup evidence are present. The post-run auditor failed
because it selected the old `R18+W2+F+V+A` condition rather than the actual
`R18+W2+F+V+A+I` condition and divided by an empty group. That separate audit
bug remains recorded, not treated as a model failure or proof of invalid task
outcomes. Full audit closure is not claimed here.

The continuous goal remains paused. No no-Pi0/1200-second experiments were started.
