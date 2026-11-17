# Tasks 3 and 4: retry with return-to-initial-pose guidance

Both retries completed on 2026-11-17 by 06:55 UTC (14:55 China time):
**0/2 native successes (0%)**, both planner timeouts, no infrastructure incidents.
Each task ran once at layout 0, starting at 05:54 UTC (13:54 China time).

| Task | Name | Result | Responses | EEF calls | Total elapsed (s) | New record |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 3 | `build_tower` | Timeout failure | 134 | 127 | 3647.5 | [b694aef3acedfe133a42](http://10.162.250.228:8094/runs?id=b694aef3acedfe133a42) |
| 4 | `classify_objects` | Timeout failure | 152 | 140 | 3647.2 | [167e72e75ec0fc532019](http://10.162.250.228:8094/runs?id=167e72e75ec0fc532019) |

Planner elapsed was 3600.7 / 3600.2 seconds; total workflow time includes ENV
startup and cleanup. Neither episode reached 200 responses or called `finish`.
Both saved native success verdicts are false. The SDK recorded interrupted turns
at the deadline, so these were not voluntary final answers followed by idle wait.

The last public summaries still describe task work: task 3 was measuring a held
block before lowering it onto a support after wrist drift; task 4 was carrying a
doll to the white basket while working the empty right arm toward its starting
pose. These are agent reports, not independently validated object states. An
offline check of final recorded EEF poses against recorded initial poses fails
the native home predicate for both episodes. The runtime's internal captured
home reference was not separately saved. This does not prove that home return
alone caused either failure or that added return guidance reduced performance.

The only changed protected source is the shared return-to-initial-pose prompt
from commit `0bbc4e4`. Astra/high, 3600 seconds, 200 model responses, 16384 output
tokens, eight EEF tools, existing v1 experience and native Codex analysis/full
access remain the same. No tower-geometry hints were added. Native actions
remain unlimited diagnostic mode, not the official benchmark.

Two durable lane workers run with serialized ENV startup and a durable monitor.
The previous worker is reused without changing its outcome policy: timeout is
failure; infrastructure incidents stop new dispatch and are excluded. The new
monitor expects two results. Both model checks passed (9.35 / 6.91 seconds) and
the six offline outcome-policy cases passed before launch. Scripts inherit the
existing network environment without changing proxy settings or IP families.

The initial launch audit verified actual submitted budgets, selected tools and
new prompt-source hashes for both episodes; all 338 protected hashes match the
new plan. All ten original outcome hashes are preserved. Old records and the
original 4/10 result are not replaced. Final validation confirms both outcome
hashes and actual budgets, all 338 protected hashes and ten original outcome
hashes. All six video files are nonempty; full decoding was not performed.
`final-results.json` is the small final summary. Full results and evidence remain
under the matching remote validation directory; `launch-summary.json` retains
the dated launch snapshot. One retry per task cannot establish a general
success-rate change. No additional episode or harness modification was started.
