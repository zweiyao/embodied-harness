# Iteration 01: approved C/E screen

Four cells: task 4 seed 0 and task 0 seed 0, each once in control C and experience-only E. Both lanes use the same tools (v3 native/generated list plus move_eef), Qwen Flash thinking off, 600 seconds, 30 requests, 16384 output token cap, direct network. Lane a=C and lane b=E; both run 4 then 0. This is a small development screen; lane assignment is confounded with condition and results are not a final success-rate estimate.

Changes to copied experiment scripts only:
- setup.py creates fresh owned workbench configs and private LIBERO configs. Each lane selects its own frozen material package. Main workbench is untouched.
- run_batch.py validates material hashes/version per lane, tags every result with C/E, keeps the prior incident policy, and refuses to start without coordinating-agent READY.json.
- preflight.py checks both frozen packages and actual memory read/write behavior, tools, budget classification, benchmark copies, proxy-free servers, then allows the batch.
- cleanup.py preserves the existing ownership and idle checks. metrics.py is unchanged from the prior EEF screen.
- Copy BDDL files to this experiment's private benchmark directory; change only task 8 language from left to right. Keep init states, official goal, installation files and benchmark_root unchanged. Both conditions use this corrected cohort. Task 8 is not executed in this iteration.

Validation: protected runtime/source hashes and original service/config before setup; per-package freeze/render/index/read-only checks; actual selected generated-tool Docker checks; real config/proxy/API preflight after READY; outcomes and model declarations audited after all four cells; initial scene parity checked within each C/E task pair. Unexpected infrastructure events are preserved and excluded, with no automatic blind retry; configured-timeout/request exhaustion remain failures.

No experiment or owned workbench starts until the coordinating agent explicitly sends READY after material and source review. Raw observations, credentials and videos remain outside Git.

Independent review repairs before launch: process-wide nonblocking flock protects both wrapper and batch; memory denial is an infrastructure incident only for a declared frozen memory file/root, while model-selected wrong/out-of-scope paths remain tool errors. Actual private BDDL routing is verified before recording each cell.
