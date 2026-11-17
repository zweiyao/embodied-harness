# Tasks 3 and 4: retry with return-to-initial-pose guidance

Two episodes started on 2026-11-17 at 05:54 UTC (13:54 China time), one per task
at layout 0. Both model sessions are running; **no final result is claimed**.

| Task | Name | New record |
| --- | --- | --- |
| 3 | `build_tower` | [b694aef3acedfe133a42](http://10.162.250.228:8094/runs?id=b694aef3acedfe133a42) |
| 4 | `classify_objects` | [167e72e75ec0fc532019](http://10.162.250.228:8094/runs?id=167e72e75ec0fc532019) |

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
original 4/10 result are not replaced. The live results are stored separately
under the matching remote validation directory in `results.json` and
`summary.json`; `launch-summary.json` is a dated launch snapshot, not a result.
