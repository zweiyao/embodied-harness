# Independent RoboDojo profile and serial component checks

The specifically approved runtime.env is installed only under remote local-setup/robodojo-integration-20261111 and is explicitly sourced in an independent shell. It pins the isolated source/resources, converted policy, release normalization statistics, independent tokenizer cache and SAM3 checkpoint, and enables the previously validated Vulkan profile. Original services and login/systemd defaults are unchanged. The profile sets upstream placement settling to 1000 steps rather than the unset default of 20; this is a separately recorded condition.

All checks used the existing RobotSpec runtime factories and current remote source. Components ran serially with no planner and no task action submission:

| Component | Observed result |
| --- | --- |
| ENV, bottles task/layout 0 | Ready in 38.55 s; two explicit dev resets passed in 8.67 / 10.87 s; task counter remained 0 after each reset |
| Observation | Three 640×480 RGB uint8 / depth float32 views, finite 3×3 intrinsics and 4×4 extrinsics, finite 14-channel joint state and official instruction |
| Pi0.5 real GPU request | One saved real observation produced finite wire shape [1,50,14], client shape [50,14]; request took 0.451 s after service startup |
| SAM3 real GPU request | One bottle prompt returned a decoded 480×640 nonempty mask; request took 0.555 s after startup |
| Cleanup | All three owned processes exited 0 before fallback cleanup; three ENV videos decoded; only the original two GPU service PIDs remained |

Weight, normalization, tokenizer and SAM3 SHA-256 checks passed. The 34 relevant source files matched the local baseline; the 608 earlier protected files were unchanged. pre-commit passed. Python source did not change, so the full unit suite was not repeated; its same-source 2043 passed / 15 skipped result remains in stage-06.

The reset checks cover one task/layout and do not establish all-task stability or prove that 1000 steps alone fixed every failure. Shapes and finite values do not independently validate metric geometry or semantic alignment. The prediction was never executed, and the SAM3 mask is not verified object identity. No benchmark result or task-success claim follows. Nine recorded dependency metadata conflicts remain. CLI/action/workbench integration is pending.

Raw observations, predictions, masks, videos, logs and the diagnostic script remain in the remote stage-07 directory. Git contains only the approved profile text and small evidence summaries.
