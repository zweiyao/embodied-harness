# Contact-response prototype

`sensor_contact_response.py` defines `run(frames, params)` using NumPy only.
Combine the fields in `contact_response_metadata.json` with a `source` field
containing that Python file to create a standard RPent perception declaration.
Pass one to four ordered frames from the sensor allowlist. The program never
reads files, simulator state, evaluator output, task IDs or hidden target poses.

This candidate was made collaboratively in the current Codex conversation from
the observable records of development runs dev-03 and dev-04. It is a manually
assisted prototype, not a controlled G0/G1 tool-making result. It has not yet
demonstrated a task-success improvement. Publication is a separate explicit
operation after replay; editing these files never changes a frozen library.

The native marker generator resamples and shuffles marker rows, and can pad
missing points with duplicates. Therefore the tool matches reference pixel
positions using mutual nearest neighbours instead of subtracting equal row
indices. Low match counts return insufficient evidence. The reference can
already contain contact. Thresholds are visible measurement settings, not
calibrated force, blockage or success thresholds.

The additional calculation is the association between recent measured hand
motions and bilateral tactile changes across time. The native `tactile_stats`
tool remains the single-frame baseline. A repeated-translation flag indicates
changing deformation while repeating a direction; it does not distinguish
normal insertion, sliding and jamming. Camera/depth evidence is still needed
for object progress and task completion. No world-frame corrective action or
hole-axis estimate is returned.

The 2026-10-26 remote Docker checks passed all five cases: marker permutation
invariance, no-match insufficiency, duplicate padding, known translation/rotation
and marker increments, and one-frame missing-sensor handling. Four historical
windows from dev-03/dev-04 also executed successfully, with 48–63 matched
reference positions per finger. These establish measurement behavior and replay
compatibility, not task improvement.

The verified declaration digest is
`33690612fb0535db929f27cf8b13f4b00b693d1555d27a08d0789a710020e9f7`.
The behavior report is at
`/home/zwy/work/embodied_harness/artifacts/univtac-audit-20261025/contact-response-behavior-v1.json`.
To repeat the synthetic checks from the remote repository, choose a new report:

```bash
PYTHONPATH=. .venv/bin/python examples/univtac/verify_contact_response.py \
  --image embodied-sensor:pilot --output /absolute/path/to/new-report.json
```

Candidate code executes only in Docker. This check uses no model or simulator.
Clarifying the task instructions is a separate intervention and must be shared
across comparison conditions rather than counted as a tool benefit.
