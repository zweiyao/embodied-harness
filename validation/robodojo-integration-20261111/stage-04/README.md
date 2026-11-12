# RoboDojo STOP callback candidate validation

The approved two-file candidate passed 165 RoboDojo tests, the full Python 3.11 suite (2043 passed, 15 skipped), and pre-commit. Both real dev and eval-fair checks failed the unchanged 45-second owned-process exit requirement. Borrowed toolkit close preserved service health. Parent cleanup eventually produced exit code 0; this is not a graceful-close pass.

The candidate targeted CollectEnv.sim, which is the Gym environment. The actual IsaacLab SimulationContext is CollectEnv.sim.sim. The test fake omitted this intermediate owner and therefore did not expose the error. The candidate was corrected after separate approval; stage-06 records passing real dev/eval-fair checks. Historical failures are retained in summary.json and in remote logs.

No planner, task action, physical robot action, proxy override or collector service change was part of these checks. Video files and raw observations remain outside Git. Runtime dependencies still have the previously recorded metadata conflicts; CPU passes do not resolve those constraints.
