# Qwen evidence v2: three-episode parallel screen

The approved screen completed three episodes with **0% success (0/3)**. All three reached the 300-second planner limit; no infrastructure incident or tool execution error was recorded. Valid failures were retained without rerunning them. No 50-episode expansion was started.

Qwen3.8 Flash, thinking disabled, 30 model requests, 16384 output-token setting, direct remote networking; `libero_10_task`, seed 0. Lane A ran task 0 then 8, while lane B ran task 4. Independent workbenches/environment processes shared the existing VLA/SAM services. The candidate used the two approved on-demand experiences and 17 native plus two existing generated tools; original prompt/controller source files were preserved.

| Task | Success | End reason | All tool calls | Action calls | Calls before first action | Batch / container calls |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0% | 300 s timeout | 27 | 0 | — | 14 / 2 |
| 4 | 0% | 300 s timeout | 22 | 4 | 15 | 4 / 0 |
| 8 | 0% | 300 s timeout | 30 | 0 | — | 22 / 0 |

The first-action mean is 15 calls among the single episode that acted (n=1); no-action episodes are excluded. Task 4's four action calls were move_to. Full recorded durations were 310.4, 311.7 and 308.7 seconds respectively, including overhead outside the planner limit.

All three episodes read MEMORY.md containing the two new index entries, but **none read either new experience body**. Thus the index was exposed, while the intended on-demand procedures were not loaded. Batch sampling was used 40 times (267 requested points). Both container calls returned `inconsistent_rim`: a geometric quality rejection, not an execution exception. Successful tool execution and adoption did not establish task benefit.

The behavior remains consistent with repeated measurement without a sufficient next-action decision: tasks 0 and 8 exhausted the budget without acting. This is an observation, not proof of a single root cause or that the new tools caused a regression. Historical v1 runs used different budgets and the present screen has no matched baseline. No success-rate, token-saving, or parallel speedup claim is supported.

Mean elapsed time for completed model request/response pairs was 12.95 s (task 0, n=22), 20.90 s (task 4, n=14), and 10.79 s (task 8, n=27). These include provider and transport time and are not pure network latency. Task 0 ended with one unfinished request, excluded from its completed-request mean.

Remote preparation passed 26 focused tests, both published helper versions in Docker, five classification and two metric cases. Final audit recomputed counts, verified exact task/seed coverage, no outside-run file reads, unchanged hashes for 776 protected files, and cleanup. Scoped Ruff passed for the final audit script. Full unit tests were not repeated because harness source was unchanged.

Both owned workbenches are stopped. Original workbench server/configuration and proxy-free networking are unchanged. Raw observations, events and videos remain remotely under `/home/zwy/work/embodied_harness/experiments/qwen-evidence-v2-screen3-20261107/`; only small summaries are tracked here. The candidate remains separately stored; original materials remain available. Further changes require a concrete proposal and approval.

Evidence: [results](results.json), [summary](summary.json), [final audit](final-verification.json), [cleanup](cleanup.json), [preflight](preflight.json), [approved scope](approved-plan.md). The read-only audit script runs alongside the remote plan/invariants and recorded episodes; it cannot replay actions.
