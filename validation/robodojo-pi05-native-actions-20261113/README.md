# RoboDojo Pi0.5 native-action validation

Approved by the user's “测试看看” after reviewing the conversion proposal.
The implementation matches that proposal, with one necessary GPU-test caller
correction: a hold command uses the native action dictionary rather than the
model input vector, whose ordering now correctly differs from native control.

The RoboDojo VLA client sends checkpoint state order L6/Lg/R6/Rg. The server
keeps RLinf unnormalization and removal of model padding, disables its incompatible
default delta inverse for this preset, restores joint deltas once from raw state,
and converts the result to native L6/R6/Lg/Rg before RPC action delivery.

Remote evidence and diagnostic scripts remain under
`/home/zwy/work/embodied_harness/validation/robodojo-pi05-native-actions-20261113`.
Candidate code is in the matching independent `checkouts/` directory.
`summary.json` records exact source hashes, test counts and bounded control checks;
raw observations, motor traces, weights and three videos remain remote.

Validation:
- Two regression tests fail on the old implementation and pass after the fix.
- 242 targeted tests; full suite 2090 passed / 16 skipped; all-files pre-commit.
- Installed RLinf transform reference: 20 states, horizon 50, 14,000 native
  values; maximum difference 2.01e-7. Grippers stay absolute.
- Real-weight prediction (50,14), 10 policy actions and controlled channel checks:
  184 native actions total, all 12 joint targets/directions and four gripper
  targets passed. Policy/controller/motor arm-target errors are zero.
- GPU component suite: four pass; the initial CLI test fails from CUDA memory
  exhaustion before ENV readiness. The same CLI chain passes separately using
  the already-running SAM3 endpoint, executes 50 native actions and records finish.
  This is not a single five-pass default-configuration GPU run.
- Strict English/Chinese Sphinx builds and rendered inline-code checks pass.
- 1776 original RoboDojo source files and 470 harnessvla source files unchanged;
  original service PIDs retained, no owned daemon residuals, three H264 files decode.

The underlying prepared stack still has nine dependency metadata disagreements;
this is not a clean-install certification. The controlled align_blocks probe's
native success is false. No external planner or complete benchmark episode was
run; correct action conversion is not evidence of task success or policy gains.
Public workbench deployment remains unchanged.
