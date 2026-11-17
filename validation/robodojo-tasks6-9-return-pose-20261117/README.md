# Tasks 6–9: retry with current return guidance

Four authorized episodes were dispatched on 2026-11-17 at 12:02 UTC (20:02 China
time), one per task at layout 0. Three durable workers run with serialized ENV
initialization and parallel execution. Lane A runs task 6 then task 9; lanes B
and C run tasks 7 and 8. No final result is claimed at launch.

| Task | Native task name | Lane | New record |
| --- | --- | --- | --- |
| 6 | `cover_blocks` | A | [736005d82909ada30dfb](http://10.162.250.228:8094/runs?id=736005d82909ada30dfb) |
| 7 | `deposit_coin` | B | [2d6a3d2f0020d801e123](http://10.162.250.228:8094/runs?id=2d6a3d2f0020d801e123) |
| 8 | `fasten_screws` | C | [cc96b0acf1fdc75abac6](http://10.162.250.228:8094/runs?id=cc96b0acf1fdc75abac6) |
| 9 | `fill_egg_holder` | A, after task 6 | Queued; record created at dispatch |

Configuration is unchanged from the current task-3/4 retry: Astra/high,
3600 seconds / 200 model responses, 16384 output-token setting, eight EEF tools,
existing v1 experience, Codex analysis/full access and the common arm-return
prompt `0bbc4e4`. No harness, prompt, tool, experience or budget change was made.
Native actions remain unlimited diagnostic mode, not the official benchmark.
There are no additional task-specific hints.

The lane worker is reused byte-for-byte. The monitor only changes its planned
result count from two to four; check and launch scripts use the new batch path
and service names. Script compilation and six existing offline outcome-policy
cases passed. All three model checks passed (9.180 / 8.792 / 6.779 seconds).
Scripts inherit networking without changing proxies, client proxy handling or
IP families. No Mac networking or real-robot operation was performed.

Preparation checked all 338 protected hashes, idle workbenches, unchanged live
configurations and available model/perception services. Of fourteen prior
episode outcomes, twelve were present and hash-matched; two previous tower
outcomes were already missing before this batch:
`ad490fba21c5d153df15` and `b694aef3acedfe133a42`. The initial preparation stopped
on that absence before creating a batch or starting an episode. The final
preparation records the pre-existing missing entries and preserves the remaining
twelve. Nothing was restored, deleted or overwritten, and missing historical
records do not count as new experiment failures.

Startup requires 11 GiB free and retains a 3 GiB reserve. Timeout counts as
failure; infrastructure incidents stop further dispatch for inspection. A durable
monitor persists live `results.json` and `summary.json` under the matching remote
validation directory. At 12:05 UTC, tasks 6/7/8 had running model sessions with
no errors; their actual submitted budgets, tools, v1 index pointer and common
return guidance were verified with matching source hashes. Task 9 remains queued
until task 6 completes. `launch-summary.json` records this initial audit, not a
final score. One retry per task cannot establish a general success-rate
improvement.
