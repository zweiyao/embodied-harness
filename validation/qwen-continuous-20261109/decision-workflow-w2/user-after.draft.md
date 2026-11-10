Experiment: {{suite}}, task {{task}}, seed {{seed}}.
Output directory: {{output_dir}}.

First response: request view_env_state(step=0), {{language_materials}}/guide.md,
and {{memory_dir}}/MEMORY.md together. The files use read_text_file.

Then start each response with NEXT=<enabled action or finish>; NEED=<missing precondition or none>.
If NEED=none, call NEXT now. Otherwise, batch only checks needed for that
precondition. Read experience for that missing fact; do not explore run logs,
prompt dumps or experiment manifests.

Use action feedback. Re-reading an unchanged frame cannot test motion.
pi0_pick executes a new grasp; do not call it merely to inspect an existing grasp.
Inspect actual feedback before the next dependent action.
