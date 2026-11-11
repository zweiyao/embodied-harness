Experiment: libero_10_task, task 0, seed 0.
Output directory: /home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/decision-workflow-w2/freeze-check/w2-t0.

First response: request view_env_state(step=0), /home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/decision-workflow-w2/freeze-check/w2-t0/language-materials/guide.md,
and /home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/decision-workflow-w2/freeze-check/w2-t0/language-materials/memory/MEMORY.md together. The files use read_text_file.

Then start each response with NEXT=<enabled action or finish>; NEED=<missing precondition or none>.
If NEED=none, call NEXT now. Otherwise, batch only checks needed for that
precondition. Read experience for that missing fact; do not explore run logs,
prompt dumps or experiment manifests.

Use action feedback. Re-reading an unchanged frame cannot test motion.
pi0_pick executes a new grasp; do not call it merely to inspect an existing grasp.
Inspect actual feedback before the next dependent action.
