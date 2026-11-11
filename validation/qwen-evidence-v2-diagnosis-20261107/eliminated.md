# Eliminated or narrowed hypotheses

- H1 (new experience index truncated/inaccessible): eliminated for index delivery. Both filenames occur in 21/25/12 model requests for tasks 0/8/4; all three files' index responses are complete at 32627 characters. The model did not read the new bodies; accessibility alone cannot ensure selection.
- H3 (batch numerical computation corrupts returned coordinates): eliminated for the 247 valid sampled patches in these records. Exact published helper replay matches all 40 calls; independent median calculation matches all valid patches. This does not establish semantic labels or physical calibration accuracy.
- H4 (tool/inference execution dominates elapsed time): contradicted by recorded tool durations, about 7.63/8.47/8.02 seconds summed across task 0/4/8, versus 284.91/292.57/291.40 seconds for completed model request/response intervals. Sums are not a mutually exclusive wall-clock decomposition when tools overlap.
- H5 (robot never moves): eliminated. Four task-4 moves executed; two reached target tolerance and two descents did not. There was no close, learned pick, transport of a held object, or release in the three episodes.
- Radius trap as sole explanation: eliminated. Task 8 used radius=2 in all 22 calls, returned 176 valid numeric patches, and still never acted.
