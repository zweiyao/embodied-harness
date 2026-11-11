# Restore the pre-loop v3 + EEF baseline

The user selected option 2: restore the state before continuous optimization,
keeping the earlier concise prompts, v3 experiences and move_eef. Baseline
revision: f7bd005. The user subsequently requested one Qwen Flash thinking trial.

## Restored behavior

The current source restores the original v3 sensor_patch_batch contract and
experience index. It removes the loop-added transfer-evidence entry,
translate_to, rotate_axis, preview_placement/align_placement, calibrated planner
view replacement, initial Pi0 action gate, finish-only output requirement and
recent-image window. The subsequent idle-retry extension is also removed to
restore the baseline planner. A text response may complete the baseline model
turn; original task lifecycle and positive wall-clock budget semantics apply.

The 20 selected tools are the original 17 native tools, sensor_patch_batch,
sensor_container_geometry and move_eef. pi0_pick remains part of this chosen
baseline. Geometry/manual tools are available from the first model request.
Published material version is qwen-evidence-v3-c6c7f677d400. Existing archived
candidate packages, experiment scripts, results and recordings remain intact;
removed current-tree code remains available through Git history.

History indexing, recorded task instructions and the standalone remote network
switcher remain. Neither Mac nor remote networking is changed by this rollback.
The original shared /home/zwy/work/harnessvla directory is preserved. The idle
LIBERO web service now uses an isolated rollback checkout; five independent
remote files are carried into it unchanged. Flexiv and UniVTAC services are not
restarted. Private configuration backups remain outside Git.

## Verification

- 15 restored files match f7bd005 byte-for-byte; Workbench and its tests retain
  only history indexing additions above that baseline.
- Remote unit suite: 2035 passed / 15 skipped, 73.51 seconds. Scoped pre-commit
  passed. Full pre-commit still reports historical validation-script issues and
  an independently preserved remote formatting difference; hook edits restored.
- 344 shared-source/material/library files unchanged during deployment. Exact
  v3 material manifest hashes and both selected generated-tool versions checked.
- All 198 existing history IDs retained. Main workbench model and budgets kept;
  its current selection changed to the baseline 20 tools. Ordinary server restart
  still initializes the original default tool selection; select/copy the v3+EEF
  configuration again when needed, as with the original workbench.
- Mac HTTP checks for the start page, history page, session configuration and
  history API passed. No policy or physical action occurred during deployment.

## Authorized single trial

Task 0, seed 0, official libero_10_task instruction and BDDL; Qwen Flash thinking
(enabled via the provider boolean), 600 seconds / 30 logical requests / 16384
output tokens, inherited direct remote networking. This uses the frozen v3
budget, not the later zero-timeout candidate. One separate lane; no continuous
optimization resumed.

Official success: false. The task reached the 600-second planner limit; recorded
elapsed time was 610.5 seconds including finalization. It issued 16 logical
requests, completed 15 responses and executed 8 action calls (2 pi0_pick,
5 move_to, 1 release). All 16 requests enabled thinking, and all 15 completed
responses contained thinking. No finish tool was called. The final response was
interrupted at the episode deadline; this is a valid budget failure, not an
unexpected incident. There were 16 HTTP attempts and no connection timeout.

Completed responses averaged 29.489 seconds (15 responses; the incomplete final
response is excluded). Fourteen image-bearing uploads averaged 7.695 seconds.
The final serialized request was 17,324,946 bytes, its upload completed in 13.401
seconds, and response headers arrived about 2.355 seconds later. This does not
separate remaining network/server waiting from model computation. Input usage
was 477,444 tokens, including 404,480 cached, and output usage was 19,564; these
accepted usage totals may omit the interrupted final response.

Every recorded request exposed the full baseline function set, including manual
motion and geometry, and allowed text output. The first pi0_pick was model-chosen,
not forced by a gate. No move_eef call occurred, so this trial does not establish
its adoption or benefit. Single-task failure does not establish general model
performance or the causal effect of thinking.

Runtime coverage and cleanup passed; 343 experiment-protected and 344 shared
source/material/library hashes remained unchanged before history publication.
The new record was then indexed without changing the restored session config;
all 198 previous IDs remain, 199 records total. Mac video range check returned
HTTP 206. The continuous loop remains paused and no follow-up task was started.

[Experiment and video](http://10.162.250.228:8092/runs?id=61bcb5efefcf9f875298)

Evidence files: change-plan.json, baseline-parity.json, independent-overlays.json,
deployment.json, software-summary.json, mac-web-check.json, trial-plan.json and
progress-update.json, final-verification.json, upload-summary.json, history-checks.json
and video-http-check.json. No credentials, videos or raw observations are committed.
