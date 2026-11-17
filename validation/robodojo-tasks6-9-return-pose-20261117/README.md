# Tasks 6–9: retry with current return guidance

All four attempts ended by 2026-11-17 at 12:50 UTC (20:50 China time).
**Tasks 6, 7 and 8 have authoritative native success; task 9 is excluded for
confirmed simulation corruption and still needs repair and a valid rerun.**
There is no complete four-task success-rate result yet. The batch was dispatched
at 12:02 UTC (20:02 China time), one attempt per task at layout 0. Three durable
workers used serialized ENV initialization and parallel execution. Lane A ran
task 6 then task 9; lanes B and C ran tasks 7 and 8.

| Task | Native task name | Reviewed result | Responses | Total elapsed (s) | Record |
| --- | --- | --- | ---: | ---: | --- |
| 6 | `cover_blocks` | Success | 99 | 1645.1 | [736005d82909ada30dfb](http://10.162.250.228:8094/runs?id=736005d82909ada30dfb) |
| 7 | `deposit_coin` | Success | 104 | 1374.7 | [2d6a3d2f0020d801e123](http://10.162.250.228:8094/runs?id=2d6a3d2f0020d801e123) |
| 8 | `fasten_screws` | Success | 123 | 1677.2 | [cc96b0acf1fdc75abac6](http://10.162.250.228:8094/runs?id=cc96b0acf1fdc75abac6) |
| 9 | `fill_egg_holder` | Excluded physics incident | 116 | 1233.2 | [13915350dda07ca0e3cb](http://10.162.250.228:8094/runs?id=13915350dda07ca0e3cb) |

No attempt timed out or reached 200 responses. Task 9's raw native verdict is
false, but its recorded state is invalid: at observation 102 / native step 503,
the largest absolute right-arm joint value jumps from about 1.83 to 7.94 billion.
The ENV server independently logs invalid PhysX transforms for an egg and the
holder lid. The agent stopped and called `finish(status="infrastructure_error")`.
The physical trigger is not yet diagnosed or repaired; the apparent final home
pose cannot establish a controlled return after state corruption.

The automatic worker missed this incident because the outer outcome error was
null and the remaining tool feedback was a recoverable range rejection. Its raw
`summary.json` therefore says 3/4 (75%). Those original records are preserved;
`reviewed-results.json` applies the already agreed rule that infrastructure
incidents are excluded. The review has three valid successes and one excluded
attempt, not a completed four-task 75% result. No runner, harness or scoring code
was changed during this review, and no additional episode was launched.

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
monitor persisted `results.json` and `summary.json` under the matching remote
validation directory. At 12:05 UTC, tasks 6/7/8 had running model sessions with
no errors; their actual submitted budgets, tools, v1 index pointer and common
return guidance were verified with matching source hashes. Task 9 was then queued
until task 6 completed. `launch-summary.json` records this initial audit, not a
final score. One retry per task cannot establish a general success-rate
improvement. Final review verifies all four outcome hashes and actual budgets,
all 338 protected hashes and twelve existing historical outcomes. All twelve
video files are nonempty; full decoding was not performed. Task 9 remains pending.
