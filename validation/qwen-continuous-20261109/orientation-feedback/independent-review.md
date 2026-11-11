# Independent R review — 2026-11-10

No actionable blocking defect found in the reviewed production change. This review made no source/test edits and initiated no environment, model request or control action. The root retains the policy-experiment gate.

Reviewed `orientation.py`, selected-only ManualToolkit dispatch/recording, owned/borrowed environment wiring, catalog/default/version behavior, relevant tests and documentation. The fixed starting position, actual controller scaling/basis, zero gripper command, bounded action count and per-step cancellation paths are consistent. The tests exercise nonidentity controller basis, injected position deviation, stalled motion, cancellation, and constant body/site offset cancellation. Reported validation is 73 focused tests and 2108 full-suite tests passed, 15 skipped; this reviewer did not rerun them.

The relative world-rotation proof is valid for a fixed mounting rotation C: `(D B0 C)(Bt C)^-1 = D B0 Bt^-1`. It does not treat the observed site position and body quaternion as a common-frame pose for reconstructing contact geometry. Installed OSC source independently confirms left multiplication in the configured world/base frame and named-site controller feedback.

Attempt01 remains a failed probe with one executed control action. Its empty trace resulted from appending after the failed audit assertion. Installed RLinf/robosuite source confirms that returned observables are cached samples, whereas the later getter reads live simulator state; their equality at 1e-7 was an invalid simultaneity assumption. The [recorded correction](probe-timing-amendment.md) changes instrumentation only, retains controller/site identity and C gates, reports cached/live discrepancies, and additionally checks final live pose against the frozen production target. No physical tolerance was relaxed.

Independently recomputed attempt02 results from its 40 robot-only trace entries:

- Actual mapping: `robot0_right_hand` body; `gripper0_right_grip_site`, site ID 11; controller reference name/ID matches in every entry; configured gripper is PandaGripper.
- Maximum change in simultaneous live body-to-site rotation is below 8e-16 rad, within the unchanged 1e-7 gate.
- X/Z positive and negative cases each execute 10 steps, with the expected signed angular progress. Final live position errors are 0.204–0.871 mm; angular errors are 0.00131–0.00248 rad, within the original 0.012 m / 0.02 rad limits. All twelve returned image files exist; this is not an independent visual grasp assessment.
- Every actual gripper command is zero; actual initialized target `[1,-1]` remains unchanged throughout. No alternate target or held object was tested.
- Attempt02 has 40 actions; including attempt01 gives 41, below the aggregate cap of 160. There are zero model/VLA calls.

Independently rehashed all 6320 protected files and all 303 source-manifest files: no differences. Recorded owned child PID/start-time identities are absent. Cleanup reports no forced cleanup, a closed facade, unchanged private/main configuration and main server, with the main workbench ready and operator inactive.

The final `source-handoff.json`, remote source and local files agree for all four production paths: orientation `7d5767d84f4e…`, manual `f4c4fdf7a3b4…`, robot_spec `740824b84107…`, workbench `17a080aad524…`. Full hashes remain in the handoff. Existing EefControl (`6fb8ea2e4023…`) and P (`3542ec64f426…`) are unchanged.

These gates establish the bounded interface in the tested clear initial pose. They do not establish large-angle/contact behavior, exact position retention along a path, collision avoidance, holding, improved recovery, or task success. They do not prove a sole cause of the historical 0.274 m drift. P remains an unpromoted parent, and R's task benefit requires the separately frozen policy evaluation.
