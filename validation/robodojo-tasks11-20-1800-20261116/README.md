# Queue RoboDojo tasks 11–20 after tasks 1–10

The operator authorized the next ten dashboard indices, 11–20 inclusive, only
after the existing 1–10 batch finishes. Each task uses layout 0 and one fresh
episode. The preparation snapshot is in `queue-summary.json`; it is a queued
configuration, not a record of completed task results.

The dispatcher requires all ten prior outcomes to be saved and valid, verifies
their hashes, waits for the old workers to exit successfully, and checks that
all three workbenches are idle. A prior infrastructure incident blocks dispatch.
The new queues cannot overlap the old batch, and a persistent launch marker
prevents a second dispatch. These jobs run on the remote host independently of
the Mac connection and chat session.

The existing workbenches and byte-identical queue/monitor helpers are reused.
Configuration remains Astra/high, native analysis/full access, indexed v1
experience, EEF-only action selection, 120 model responses, and 1,800 planner
seconds. At most three environments run concurrently, with serialized
initialization and the existing GPU memory guards. Native actions remain
unlimited in development mode, so these are not official-budget evaluations.
Timeouts remain failures; infrastructure incidents are excluded and stop new
dispatch. No harness source, experience, proxy setting or Mac network is changed.

| Dashboard index | Task | Lane |
| --- | --- | --- |
| 11 | fold_clothes | A |
| 12 | fold_clothes_random | B |
| 13 | general_pickup | C |
| 14 | hang_mugs | A |
| 15 | hang_mugs_random | B |
| 16 | imitate_sorting_sequence | C |
| 17 | insert_key | A |
| 18 | insert_tubes | B |
| 19 | make_kong | C |
| 20 | make_toast | A |

Remote evidence is under
`/home/zwy/work/embodied_harness/validation/robodojo-tasks11-20-1800-20261116/`:
`plan.json`, `queue-summary.json`, `dispatch-status.json`, `dispatch-started.json`
(only after the prior batch finishes), and the usual per-lane/current/result
artifacts after dispatch. The waiting service is
`rpent-robodojo-11-20-after-previous-20261116.service`.

Validation: remote Python compilation; hashes of the copied queue helpers;
exact ten-task inventory/range, unchanged planner configuration and protected
source/experience hashes. The scheduling check records the live dispatcher
state and checks that no new task was launched while the old batch was active.
These are scheduling checks, not task success or a new harness test result.
Raw observations, recordings, credentials and private configuration are retained
only on the remote host.
