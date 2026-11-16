# RoboDojo owned ENV shutdown correction

The approved correction clears the public IsaacLab SimulationContext at CollectEnv.sim.sim after video flush and before the existing RLinf/native teardown. The intermediate Gym environment is preserved in the regression fixture. No private Isaac callback fields or upstream source files are modified.

With the corrected fixture and old runtime call, all three close regressions failed with AttributeError. After the fix: 165 RoboDojo tests passed; full Python 3.11 tests reported 2043 passed / 15 skipped (72.70 s); pre-commit passed. This is one Python environment, not the full CI matrix.

Real dev and eval-fair checks both passed the unchanged 45-second requirement: borrowed toolkit close preserved health; owned ENV close exited with status 0 before parent cleanup; each of three camera videos decoded. Historical failures remain in stage-02 and stage-04, and this result does not certify repeated reset stability or task success.

The simulator alone used the existing Vulkan compatibility profile. No planner requests, task action calls or physical hardware actions ran. The 608 original guarded source/config files remain unchanged. Existing workbenches and the operator's collector were observed active and were not restarted or reconfigured by this work. See summary.json for conditions and remaining checks.
