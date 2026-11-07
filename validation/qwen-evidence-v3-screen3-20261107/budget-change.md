# User-requested 600-second budget

After v3 tasks 0/4 had started at 300 seconds, the user requested 600 seconds. Their active workbench processes and frozen budgets remain unchanged. Only the external batch controller was stopped, updated and resumed; it adopted the existing episodes without reset or redispatch. Task 8, not yet started, uses 600 seconds. The three-cell scope, memory, tools, max_turns=30 and other settings remain unchanged. Summaries separate actual budget cohorts.

Five timeout-classification and four controller cases passed, covering active adoption, completed-but-unrecorded adoption, next 600-second dispatch and refusal to alter a pending episode budget. Live checks confirmed each workbench kept its original server ID and exactly one 300-second run. Original controller/plan/status are archived remotely under budget-transition-600/. No new baseline or extra episode is authorized by this adjustment.
