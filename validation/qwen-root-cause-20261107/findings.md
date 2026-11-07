# Symptom

Qwen often spends many calls before its first action and fails manipulation tasks. Empty-library runs still include repeated perception and zero-action timeouts. Prior concise-prompt screening improved some selected cases but is not a controlled efficacy result.

# Scope

Read-only analysis and historical replay of original Qwen 50, concise-prompt 8, empty-memory 10, plus Astra comparator logs. Identify the earliest supported failure mechanism and draft narrow reusable experience/procedure candidates. No new experiments or production modifications.

# Iterations

Six iterations are recorded in hypotheses.md. The completed evidence narrative is [report.md](report.md); exact unapproved memory drafts and isolated comparison scope are in [proposal.md](proposal.md).

- Confirmed local defect: artifact directory/frame-path ambiguity.
- Supported mechanism: perception is not bounded by the next primitive's actual evidence requirements; semantic referents and object-relative action state can drift.
- Confirmed reusable capability: two existing optional geometry tools were absent from all 128 episode declarations; one was replayed on an archived frame successfully.
- Not established: improved task success, token savings, causal superiority of experience or tools, independent calibration accuracy, physical reason for motion stalls.
- No new environment actions, no runtime behavior changes, no candidate memory deployment.
