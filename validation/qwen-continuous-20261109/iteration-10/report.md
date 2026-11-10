# Iteration10: earlier action without task success

R18+W2+F+V+A achieved **0% (0/2)** on task0/4 seed0. Both reached the full600s
planner limit and remain valid failures; outcome elapsed611s includes finalization.
A is not promoted. C remains the historical two-cell reference (1/2), not a
validated estimate of general capability or a fresh matched comparison.

| Task | Requests / completed | Actions | Calls before action | First action from first event |
| --- | --- | --- | --- | --- |
| 0 | 11 /10 | 5 | 5 | 46.620s |
| 4 | 12 /11 | 4 | 7 | 81.728s |

09 had10/13 calls before action and228.029/213.346s. A actually exposed nine
initial tools, then18 after the first recorded nonzero-chunk language action.
All actual request schemas and both phase transitions passed the terminal audit;
there was no geometry dispatch before the transition. This supports adoption of
the workflow, not success benefit. Timing/model sampling remain confounds.

## Failure sequence and limits

Task0 picked the cream-cheese box with the native heuristic true after18 chunks.
The external step1 frame shows the cheese between the fingers above its initial
surface, supporting pickup but not yet stable transport. Before measuring the
basket, the model requested a far translation and, after a large residual,
requested an even farther target along that component. Both80-step moves stalled
near the same EEF pose with residual0.1473m/0.1912m. Step3 shows the arm extended
toward the near image edge and the target cheese outside the view, so stable
holding at that point is unverified. The basket was segmented only afterwards.
Its measured location differs substantially from the earlier guessed targets.
Later moves attempt recovery but neither release nor the second object occurs.
This sequence implicates unsupported target choice and poor response to stalled
motion; it does not establish a broken coordinate transform or the exact physical
joint/contact cause of the stall.

Task4 picked and visibly carried the yellow/white mug. Its step2 image has the
mug at a different position from the first preview's held_feature selection,
which falls on the table. The tool uses [row,column], not [x,y]: the selected
plate polygon is at the image-left plate, not the top background. Do not diagnose
an axis swap by reading its arguments as Cartesian image coordinates. The later
preview corrects the held point, computes a long XY correction and requests an
intermediate waypoint. After that move, another preview and alignment occur.
There is no release and no second-object action before timeout. P is adopted,
but repeated manual feature/plane selection consumes decisions and waiting time.

The three inspected640px analysis previews and their source hashes are listed
in visual-review-provenance.json. Originals and policy image bytes are unchanged;
images remain outside Git. No claim is made about frames not inspected.

## Image history and next hypothesis

image-history-census.json records each actual request's image artifacts and
end-to-end completed wait. Final requests carried15/18 images,10.94/10.23MB raw
image bytes before wire encoding. The last completed waits were97.15/112.05s.
Twenty-one completed waits total1044.170s (mean49.722s). The same two-image input
can also have substantially different waits, so this is not a causal latency
experiment or a network/inference decomposition. Pending final waits are null.

The next independent hypothesis is bounded image history: retain the newest two
image-bearing request groups and all text/tool history, preserve saved images
for explicit read_image recovery. This may reduce redundant payload and old/new
frame confusion, but can lose useful visual context or prefix-cache hits. It
requires a default-off implementation, actual SDK request tests and a fresh
screen before any task-benefit claim. No proxy or transport change is proposed.

## Audit and cost

12880 protected hashes, full contemporaneous child coverage, F/V/A flags,
frozen W2 materials, image/frame bindings and owned cleanup passed. All units
are inactive/MainPID0/exit0. Runtime incidents:0. No valid failure was replaced.
The65 runner cases passed. Initial runner lint used the workspace's inherited
rules; unchanged helpers were restored, then formatting/import checks passed
using the repository config from the candidate source directory. The first
import-order failure log is retained; no policy task existed at that point.

Costs:23 requests,372063 input tokens including283904 cached,2134 output tokens,
1222.0 summed outcome seconds. Two connectivity checks are separate. Cumulative
01–10:24 valid development attempts,409 requests; do not pool distinct versions
into a success-rate estimate. Ten-task frozen coverage and fresh50+50 evaluation
are still outstanding. Fewer preparation calls alone has not met the objective.
