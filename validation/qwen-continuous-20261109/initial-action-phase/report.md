# Initial action phase: software validation

The opt-in candidate A is implemented in five production files. It exposes
identity/read tools and selected language primitives first, then the remaining
selected tools after a new recorded language-action step with nonzero chunks.
A failed pickup heuristic still unlocks recovery. Default behavior and the
original workbench remain unchanged. This is a workflow experiment, not a
validated success-rate improvement.

Remote source: `/home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/initial-action-phase-test-checkout`.
Parent is the frozen V checkout from09. Setup verified all303 parent source
hashes and copied its existing supporting examples, tests and memory fixtures.
Final verification found exactly the five planned production differences and
confirmed the parent hashes unchanged. Source-handoff records the candidate
bytes, F/V modes and unchanged motion/placement/orientation provenance.

## Checks actually run

- Installed-SDK, manual-toolkit and workbench suites:145 passed in5.53s.
  Dynamic exposure changes on the next actual SDK model request. Attempting a
  hidden tool cannot dispatch it; direct adapter dispatch also rejects it.
  Finish is still accepted while locked. Actual ManualToolkit state recording
  confirms successful/failed nonzero-chunk pickup unlocks manual translation;
  readonly, invalid-argument and zero-chunk calls do not. Server ownership,
  explicit factory propagation and claimed-task config freeze are covered.
- Eight changed production/test files: scoped pre-commit passed. The first
  scoped run sorted one import, and the subsequent run passed.
- Full remote offline suite after hooks:2168 passed /15 skipped in75.83s.
- All22 native catalog records and native/calibrated default selection prompts
  equal parent V. All seven W2 files match the frozen material manifest.
- Full pre-commit remains unsuccessful:18 diagnostics in historical validation
  scripts. Its output is retained separately; no unsafe fixes or unrelated
  local source edits were applied. This is not reported as a clean full hook run.

Commands from the candidate root used `/home/zwy/work/harnessvla/.venv/bin/python`:
`-m pytest tests/unit_tests/rpent/planner/test_api_contracts.py tests/unit_tests/robots/libero/research/test_manual.py tests/unit_tests/rpent/dashboard/test_workbench.py -q`,
`-m pre_commit run --files` with the eight files listed in setup.json,
`-m pre_commit run --all-files`, and `-m pytest tests/unit_tests -q`.

The first focused run retained two fixture failures (143 passed): TestModel
was incorrectly configured to call output finish as a function tool, and the
workbench test had not set its required connection-check state. Corrected those
fixtures without changing production behavior or relaxing the expectations.
An initial import-order lint failure preceded that first test run. All final
checks above ran against the formatted candidate. Full Python CI matrix and
real simulator/model behavior remain unverified for A.

Software validation made zero external model requests and zero simulator
moves. No episode, proxy or Mac network setting was changed. The next step is
a separately frozen two-cell task0/4 screen, auditing per-request tool exposure
against the recorded phase and actual primitive chunks. Reduced preprocessing,
tool adoption or apparent partial progress alone cannot promote this candidate.
Ten-task frozen coverage and independent50+50 evaluation remain outstanding.
