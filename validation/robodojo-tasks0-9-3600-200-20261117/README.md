# RoboDojo tasks 0–9: final results

Completed on 2026-11-17 at 04:25 UTC (12:25 China time): **4/10 successes (40%)**,
6 failures, 10 valid unique episodes and no infrastructure incidents. Each task
was attempted once at layout 0. Task 7 exhausted the response budget; task 8
hit the planner deadline. Tasks 3, 4, 6 and 9 ended without native success.

Configuration: Astra/high, 3600 seconds / 200 model responses, 16384 output-token
setting, current eight-tool EEF selection, native Codex analysis/full access,
existing v1 indexed experience, and grasping-arm-only closure prompt `a2d84b8`.
Native actions remain unlimited diagnostic mode, not the official benchmark.

| Task | Native task name | Result | Responses | Elapsed (s) |
| --- | --- | --- | ---: | ---: |
| [0](http://10.162.250.228:8094/runs?id=4a931a228d6ac8abc262) | `align_blocks` | Success | 48 | 771.3 |
| [1](http://10.162.250.228:8094/runs?id=e3aff58602d9573fcfef) | `arrange_largest_number` | Success | 97 | 1029.0 |
| [2](http://10.162.250.228:8094/runs?id=1033d1cc3a3c1423c13f) | `arrange_largest_number_random` | Success | 136 | 3196.6 |
| [3](http://10.162.250.228:8094/runs?id=ad490fba21c5d153df15) | `build_tower` | Unsuccessful | 130 | 1472.1 |
| [4](http://10.162.250.228:8094/runs?id=52bf4af84c0e4a816467) | `classify_objects` | Unsuccessful | 124 | 1392.1 |
| [5](http://10.162.250.228:8094/runs?id=3623737482865b9f2110) | `classify_objects_by_language` | Success | 131 | 1602.4 |
| [6](http://10.162.250.228:8094/runs?id=6a0ed122853d17fdb8db) | `cover_blocks` | Unsuccessful | 91 | 1025.3 |
| [7](http://10.162.250.228:8094/runs?id=8876b4a8bc00b3a26861) | `deposit_coin` | Response limit | 200 | 2696.4 |
| [8](http://10.162.250.228:8094/runs?id=c192b749c15277d309a3) | `fasten_screws` | Timeout | 174 | 3647.2 |
| [9](http://10.162.250.228:8094/runs?id=e630aa6a1987f1071ffa) | `fill_egg_holder` | Unsuccessful | 29 | 413.1 |

Across all ten episodes, mean model responses are **116.0** and mean recorded
elapsed time is **1724.55 s**. The elapsed value includes the full task workflow,
whereas 3600 s is the planner/model-and-tool budget. Provider-reported input plus
output totals 128,927,548 tokens, including repeated/cached inputs; this is not
a monetary cost estimate.

Validation: all ten saved outcome hashes and actual 200/3600 configurations
match; all 338 frozen source/experience/runner hashes remain unchanged. Three
nonempty video files are present for every episode (30 total); full video
decoding was not performed in this final audit. Native success, not planner
completion text, determines success, with timeout counted as failure.

Preparation retained prior launcher bytes before updating the two active
launchers and live session defaults. Other environments and model/tool/token
settings were unchanged. Three durable lane workers used serialized ENV startup,
11 GiB startup headroom and a 3 GiB reserve; peak usage was 40167/49140 MiB.
Script checks, six offline outcome-policy cases and three model connection
checks passed before dispatch. Actual initial episodes also passed prompt-source
and submitted-budget verification. `launch-summary.json` retains that dated
launch snapshot; `final-results.json` is the final small result summary.

All raw records, videos, full plan/hash list, startup backups and per-lane
logs remain outside Git under
`/home/zwy/work/embodied_harness/validation/robodojo-tasks0-9-3600-200-20261117/`.
No raw observations, recordings, credentials or weights are committed. Budgets
and task coverage differ from the earlier 1800 s / 120-response batch; with one
episode per task, this result does not isolate the effect of the prompt change.
