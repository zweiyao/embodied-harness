# Iteration 04: restricted18 C+M

The coordinator authorized this reviewed condition and launch after a clean preflight. This is a new immutable experiment directory. Iteration 03, its source checkout, all earlier results and the main workbench stay unchanged.

The only selected-ID change from iteration 03 is:

```diff
- native:move_to
- native:move_pose
- native:move_eef
```

The other 18 IDs retain their original order, versions, schemas and descriptions; the complete before/after selection is in `selected-diff.json`. C material `qwen-evidence-v3-c6c7f677d400`, the two original generated tools, and M version `6711255f161f2c32649b31f6c2ff8055f5c8544bfbdca507ce66fa4daac280af` remain frozen. The verified `motion-contract-test-checkout` is reused read-only. No source behavior, memory, tool description or prompt sentence is added. The existing M guidance remains; there is no extra name-mapping sentence.

Lane a runs task 4 seed 0 and lane b task 0 seed 0, once each, with Qwen Flash API thinking off, 600 seconds, 30 model requests and 16384 output tokens. Both use cleared proxy variables, the isolated `RPENT_REPO_ROOT`/`PYTHONPATH`, and the same private `libero_10_task-language-right-v1` cohort. The primary development reference is iteration-03 C+M with 21 tools; iteration-01 C is retained as a separate reference.

The hypothesis is that restricting alternative position tools will expose M's actual execution behavior after two zero-adoption cells. This is a change in available control capability, not a capability-preserving alias: arbitrary pose/EEF targets and translation-time optional gripper/yaw arguments are removed. Pi0, separate rotations, gripper tools and release remain. Those tools can still cause grasp, orientation or premature-release failures, and Pi0 may still be used instead of M. Old guide references to disabled tools remain; misuse or skipping transport is valid model behavior, not an infrastructure incident.

Removing `move_eef` also means the environment should not receive `--enable-eef-control`. M does not require that controller RPC; underlying OSC settings are unchanged. Preflight runs targeted existing selection/registration tests, checks 18 selected tools and the xyz-only M schema, then verifies memory, published tools, source roots, budgets and direct connectivity. It does not rerun the full source test suite or perform an extra simulator trial.

During actual episodes the live audit checks 17 function tools plus one finish output tool, no hidden removed tools, both environment command lines without the EEF flag, the isolated source roots and absence of all six proxy variables. Final auditing recomputes metrics, verifies each retained tool's version/schema/description against iteration 03, compares initial images with both references, checks frozen files, and cleans up only owned services.

M requests, non-error returns and observed movement are separate evidence. The inherited `steps_used` and recorded-step indicator are not actual controller-action counts or proof of transport; motion and holding require pose/frame review. Adoption alone is not improvement. Official success and complete request/time/token costs include every valid failure. Unexpected incidents are preserved and investigated before rerunning the affected cell; a full time-budget expiry or request-budget exhaustion remains failure. Two development cells cannot estimate ten-task success rate or establish a causal tool benefit.
