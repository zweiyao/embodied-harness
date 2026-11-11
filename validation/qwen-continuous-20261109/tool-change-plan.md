# Approved tool candidate T: alignment_pair

The user approved the displayed first-round proposal and bounded continuous optimization. This change implements only the optional sensor_patch_batch alignment_pair calculation; it does not implement EEF feedback changes, alter native motion, publish a tool, or start an experiment.

Files: examples/manual-workbench/sensor_patch_batch.py, examples/manual-workbench/candidate.json, tests/unit_tests/robots/libero/research/test_high_resolution.py.

Before: the helper returns patch world positions and EEF offsets; callers compose transfer targets manually. After: optional [object_index, goal_index] produces a conditional XY-alignment EEF target at unchanged height. It requires an explicit latest recorded step, two different valid point indices, usable sampled surfaces, and finite EEF position. Other calls retain existing output. The latest-step gate does not establish semantic identity or tracking. Holding, unchanged orientation and correct same-frame points remain stated conditions.

Validation: remote isolated checkout; mathematical translation-equivariance, pair reversal, preserved Z, default-output compatibility, stale/latest-step boundary, invalid pairs, invalid depth/EEF, schema and source parity; focused research tests and scoped pre-commit. No new model requests or simulator actions. Full suite is coordinated by the parent agent.

Independent remote differences checked before edits: live harnessvla examples and tests still lack the previously approved radius>=1 correction present in the local repository and previous lint checkout. Live examples/tests will not be overwritten. Candidate T starts from the approved corrected local source and must be published later as a separate immutable tool version. Existing library versions remain intact.
