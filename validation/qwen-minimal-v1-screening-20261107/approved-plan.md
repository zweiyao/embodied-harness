# Draft only — not deployed

Scope: Qwen Flash LIBERO only, external language package. Core harness, native tools, original v1 package, system prompt, original guide and memory remain untouched. No new generated tools or experiences. Applies to procedural interaction guidance, not task-specific trajectories.

Exact content change: copy verified v1 material package into a new immutable experiment package, then append a blank line plus user-append.txt to user.md. All other material bytes identical. Rebuild manifest hashes and give the copy a new version. Original user.md bytes remain the prefix of candidate user.md.

External workbench config copy: change only language_materials from /home/zwy/work/embodied_harness/language-materials/v1 to /home/zwy/work/embodied_harness/language-materials/qwen-minimal-v1. Original workbench.json unchanged. Select copy through existing RPENT_WORKBENCH startup setting; isolate output paths and record run provenance. Do not commit copied credentials.

Checks before experiments: verify original source/material hashes unchanged; verify only user.md differs in candidate package; test freeze_materials and prompt rendering in a temporary output directory on remote; retain required native tool declarations and budget. These checks do not establish success gains.

Stage1: 16 screening episodes, tasks0,4,6,8 seeds0,1 under paired baseline versus all-three-guidance candidate. Qwen profile, 17 tools,1500seconds,30requests,max_tokens16384 unchanged. Alternate baseline/candidate order within pairs to reduce service-time confounding. Fresh baseline required; do not compare mixed historical budgets as a matched control.
Metrics: official success primary; first action request index, reads, localization calls, argument errors, actions without reaching their target, elapsed time, input/output tokens secondary. Full timeouts/turn exhaustion count as failures; unexpected incidents excluded and handled before same-cell retry. Use qualitative case review for grasp/placement claims, not heuristic tool success alone.
Selection: candidate needs more paired successes to be promising; lower calls/tokens alone is insufficient. With only8 pairs this is screening, not significance or generalization proof. If promising, propose paired held-out-seed validation before claiming improvement. If unsuccessful, diagnose per module and prepare the next precise short draft; no hidden prompt changes.
Restore original workbench config and proxy environment after tests. Record results, update progress, commit/push and update open PR; do not merge.
