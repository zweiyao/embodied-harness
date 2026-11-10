# R orientation feedback: implementation and interface validation

R is implemented and frozen in a new isolated checkout. Remote software checks and the bounded robot-only simulator probe pass. No Qwen policy episode has used it yet, and no grasp or task-success improvement is established. Frozen P remains the source parent, without being promoted on its 0/2 task result.

## Change

`rotate_axis(axis, angle_rad)` accepts a relative world-X or world-Z rotation without a model-supplied quaternion or gripper command. It freezes the starting position and orientation target, then uses unchanged `move_eef` feedback in at most four ten-step chunks. The active controller supplies action scaling and coordinate basis. Existing position/angular defaults are read from native declarations; the tool reports measured residuals and actual action count. It retains the gripper command target, not a claim of holding.

The only production paths changed from P are new `robots/libero/research/orientation.py`, selected-only ManualToolkit registration/guidance, the existing controller-feedback spawn condition in `robots/libero/robot_spec.py`, and default-off catalog registration. Original tools, M, P geometry, EEF conversion, controller getter/RPC, API/session/image paths and existing memory are unchanged. The planned screen explicitly replaces `rotate_wrist` and `rotate_pitch` with this single tool: P19 becomes18 selected tools.

The source checkout is `/home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/orientation-feedback-test-checkout`. Its303-file manifest in [source-handoff.json](source-handoff.json) is authoritative; the copied checkout's older Git HEAD does not describe its verified working tree. The local repository has the same four production file contents. R's module/tool hash is `7d5767d84f4eb55ca2d38ae0d96fbaf4ac1a08ab256ac8694136347c0cfb15f1`. M and both P tool versions are unchanged.

## Software verification

- Remote full units: **2108 passed /15 skipped**,73.54s, installed Python3.11 environment. This does not cover the full CI Python matrix.
- Focused rotation/manual/EEF/workbench tests: **73 passed**. They exercise nontrivial starting rotations, independent coordinate-basis/scaling checks, injected position deviation, finite stall/count behavior, zero/invalid inputs, cancellation/truncation, normal selected-tool dispatch/recording and owned/borrowed environment routing.
- All21 old native catalog records are identical to P, including source, description, schema and version. Six default/non-R prompt snapshots are identical. The new tool is off by default.
- Scoped production/test hooks and validation-script hooks pass. No whole-repository hook pass is claimed.

The first focused run had71 passes and two failures from an algebraic test's unintended `atol=0` comparison with analytical zeros; observed roundoff was4.16e-17. The test now has an explicit eight-float64-epsilon allowance, with zero relative tolerance. No production or physical gate changed. The original failure log remains remote.

## Simulator probe and retained failure

Attempt01 stopped after one actual action because its audit compared cached robot observations with a later live simulator snapshot at1e-7m. Their measured difference was60.5µm. Installed source and independent review confirmed that control-rate cached observations need not represent the final physics substep. This was a validation instrumentation error, retained as a failed attempt. Its native recording has one frame; the empty trace did not mean zero actions. Its exact script, execution audit and cleanup remain archived.

The recorded [timing amendment](probe-timing-amendment.md) changed only audit instrumentation. Body/site rotation C is computed from one live robot snapshot; reference site names/IDs remain checked. Cached/live discrepancies are reported separately. Both original reported pose gates and additional live final-pose gates apply; no physical tolerance was relaxed. Attempt02 had159 actions remaining under the aggregate160-step cap.

Attempt02 completed four calls with10 actual steps each. Aggregate actions including attempt01 were **41/160**. It used zero model requests and zero VLA predictions. The controller wrapper was enabled and normal ManualToolkit action recording returned three images per call.

| Diagnostic rotation | Actual steps | Final live position error | Final live angular error |
| --- | ---: | ---: | ---: |
| World X +0.08rad | 10 | 0.871mm | 0.001704rad |
| World X -0.08rad | 10 | 0.841mm | 0.001310rad |
| World Z +0.08rad | 10 | 0.207mm | 0.002446rad |
| World Z -0.08rad | 10 | 0.204mm | 0.002482rad |

All meet the unchanged0.012m/0.02rad gates, with nonzero correct-sign motion. The actual controller reference and observed site are both `gripper0_right_grip_site`; the quaternion body is `robot0_right_hand`, with PandaGripper on FixedBaseRobot. Across all40 live samples, body-to-site rotational offset variation was at most7.78e-16rad, below1e-7. Thus the constant-offset condition for relative global residual cancellation is supported for this installed robot. This does not make mixed body-quaternion/site-position observations a common pose for arbitrary pad reconstruction.

The actual initialized gripper target **[1,-1]** remained exactly unchanged, and every transmitted gripper command was zero. Under the installed PandaGripper mapping this is the open target; closed/partial targets and held objects were not tested here. Maximum cached/live discrepancy was60.86µm and0.000665rad. These are explicitly separate from pose-arrival error.

Both attempts cleaned up their owned children without forced termination. After attempt02, all6320 protected files remained unchanged; the original workbench retained its server/config, was ready, and had operator activity off. Raw robot traces/images/video/private config remain remote. Local summaries contain derived validation measurements, not original observations.

## Limits and handoff

The probe tests small rotations at one initial pose. It does not establish large-angle reachability, collision avoidance, grasp recovery or held-object transport. Historical04's0.274m drift remains observed but not uniquely explained by the old scaling assumption: contact and coupling were not isolated. The optional controller interface now has evidence sufficient for a separately authorized screen; whole-task outcomes and costs must determine whether to retain the candidate.

The remote handoff records successful probe/cleanup paths, exact versions, the failed first attempt and aggregate budget. Root owns the subsequent screen decision, Git/PR and board updates. No network transport, image encoding, experience or policy experiment was changed by this implementation.
