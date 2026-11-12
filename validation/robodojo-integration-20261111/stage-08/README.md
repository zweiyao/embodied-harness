# Bounded native RoboDojo action diagnostic

The user-approved single run used one bottles task/layout 0 environment and the previously approved profile. It called the real toolkit eight times: each arm moved 2 cm above its current EEF position and back, then received close/open commands. The script's pre-dispatch action guard was active; no planner or VLA was called.

The scripted assertions passed. Each tool call consumed one native action, for eight total. Four move errors were 1.74–2.10 mm, the largest unselected-arm drift was 0.026 mm, and all eight calls produced a new state record with three images. Invalid 13-channel and nonfinite 14-channel vectors were rejected without advancing the counter. The owned process exited 0 before fallback cleanup; all three videos decoded. The 608 protected files remain unchanged.

Two production contract gaps remain:

- The startup argument max_episode_steps=96 did not change the native tool's reported step_limit=700. The RPC adapter bypasses RLinf.step, where the configured cap is normally enforced, and its own pre-dispatch check only uses the official task limit in eval-fair. This test did not approach either limit and remained bounded by its diagnostic client.
- set_gripper returned closed while actual normalized opening was about 0.65248 after one control interval. After open it was 1.0. This confirms the direction but does not demonstrate a completed close. The tool currently labels the requested target without checking the returned state.

The proposed remedies are an effective RPC cap equal to the smaller of the configured and official limits, and explicit commanded/target/measured gripper feedback. They remain drafts and were not applied. No waiting loop, force, velocity, control parameter, experience or prompt was changed.

Only small evidence and the approved diagnostic source are committed. Raw trajectories, observations, action targets, video and logs remain in remote stage-08/run-01. Task success, VLA action execution and unified workbench integration remain unverified.
