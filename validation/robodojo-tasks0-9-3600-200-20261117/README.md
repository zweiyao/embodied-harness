# RoboDojo tasks 0–9, 3600 seconds / 200 responses

The user approved increasing only RoboDojo's planner budget to 3600 seconds and
200 model responses, then requested one run of each native task numbered 0–9.
All use layout 0, Astra/high, the current eight-tool EEF selection, native Codex
analysis/full access, the existing v1 indexed experience corpus, and the approved
grasping-arm-only closure prompt (`a2d84b8`). The native action cap remains zero
(unlimited diagnostic mode), so this is not an official benchmark protocol.

The three live workbenches and their future launcher defaults have the new
budgets; other settings and other environments' configurations are unchanged.
`budget-change.patch` records only the two requested flag changes. Prior launcher
bytes and hashes were backed up before changing these active service launchers;
completed experiment plans, worker scripts and outcomes retain their old budgets.
No services or networks were restarted or switched.

A durable worker per lane uses serialized ENV initialization, at least 11 GiB
free before starting another ENV, and a 3 GiB reserve. Assignments are A: 0/3/6/9,
B: 1/4/7, C: 2/5/8. A separate monitor persists results and status independently
of the chat. The existing batch runner is copied into this new directory; only
its timeout handling is clarified so a timed-out initialized episode remains a
failure when its final native verdict is absent. Infrastructure incidents remain
excluded and stop new dispatch; already launched episodes are never resubmitted.

Prelaunch checks: script syntax and compilation pass; six offline outcome-policy
cases pass; real model checks pass in 10.325/5.953/6.029 seconds. Launch audit
checks the actual saved budgets and prompt source hashes on all three initial
episodes. All are running without reported errors, the monitor/three workers are
active, and 338 source/experience/runner hashes are unchanged. GPU usage is
38646/49140 MiB at this snapshot. These are launch checks, not task successes.
`launch-summary.json` is a dated snapshot; consult remote `summary.json` for live
progress rather than treating the initial zero completions as a final result.

Run records and videos appear at http://10.162.250.228:8094/runs. Raw evidence,
full plan/hashes, startup backups, copied workers, policy fixtures, connection
checks and live per-lane/results/summary JSON remain outside Git under
`/home/zwy/work/embodied_harness/validation/robodojo-tasks0-9-3600-200-20261117/`.
No raw observations, recordings, credentials or weights are committed. Earlier
1800-second/120-response runs are different conditions; this batch does not by
itself isolate a prompt effect or establish a success-rate improvement.
