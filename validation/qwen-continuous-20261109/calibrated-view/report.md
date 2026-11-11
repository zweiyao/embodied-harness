# V: optional calibrated planner views

The independent LIBERO manual-workbench candidate now supports server-owned
`planner_view_mode: calibrated-pair-v1`. The default remains `native`.
Automatic view/action feedback attaches saved calibrated external and wrist
high images, in that order, with image_views binding each image's artifact,
camera, resolved step and actual dimensions. Bytes are not transformed.
Explicit policy-image reads remain available and are labeled policy.

The four production files are the exact scope recorded in change-decision.md.
F finish-only gating,18 selected tools,W2 seven material files, stored observations,
VLA inputs, calibration, controller parameters and task budgets are unchanged.
The original workbench has not been switched to this mode.

Remote validation on the isolated calibrated-view-test-checkout:

- Final full suite: **2154 passed / 15 skipped**,71.75s. The complete multi-Python
  CI matrix was not run. Initial focused suite:69 passed; the full run also
  covers additional registered view/read dispatch assertions.
- Both view and automatic action paths return the same saved byte sequence with
  correct bindings; explicit reads preserve policy/unknown frame distinctions.
  Missing/corrupt required files return an error with no partial bundle. Tests
  cover different sizes/steps, default behavior, server ownership, frozen task
  serialization and CLI→factory propagation.
- Three archived observations from08 replayed through the actual presentation
  code. Candidate high images equal saved bytes; default native image/data hashes,
  all22 native catalog entries and the default selection prompt match F exactly.
  This verifies image provenance, not target identity, stable grasp or success.
- Parent303 production-source hashes remain unchanged; the candidate differs in
  exactly four files. W2 seven files match their frozen manifest. Six changed
  production/test files passed scoped pre-commit; replay script Ruff passed.
- Zero real model requests and zero simulator actions for this software phase.

Validation failures are retained. The first catalog assertion compared the
combined workbench catalog with an undecorated native catalog; the expected
construction was corrected, retaining every field. The first full suite had14
failures because the fresh clone omitted nine parent example/memory support
files; exact parent bytes were restored into the owned candidate only. No
production behavior or success criterion changed to accommodate these failures.

The full repository pre-commit check failed on historical validation scripts
(274 remaining errors after its fixes). Its resulting noncandidate tracked
files already matched the parent checkout; no additional restoration was needed.
A final full unit run was performed after all hooks to remove ambiguity from a
prior overlapping check. The full hook log remains remote at
`/home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/calibrated-view/precommit-all.log`;
small summaries and failure logs are retained here. No unrelated historical
formatting edits are included in the implementation commit.

Selected action implementations return data without their own image prefix;
the shared scheduler appends automatic feedback. Tests exercise Pi0,translation,
placement alignment and rotation through that path. Segment and placement
preview retain their separate image contracts. This scope must be revisited if
an action begins returning native images before feedback.

Task efficacy is **unverified**. The next frozen screen uses task0/4 seed0,
600s/30requests,Flash nonthinking, two environments. Compare with08 as a
historical parent and retain timing/lane caveats. V is a presentation package
(thumbnail removal plus frame labels); its components are not independently
identified by that comparison, and it may not fix semantic target substitution.
