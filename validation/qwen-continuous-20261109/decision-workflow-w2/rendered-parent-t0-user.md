Experiment: libero_10_task, task 0, seed 0.
Output directory: /home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/decision-workflow-w2/freeze-check/parent-t0.
Inspect the initial recorded scene to obtain the actual task instruction.
Read the guide and index, then choose the next available primitive. Read experience
for its unresolved blocker. Resolve only the evidence that primitive needs;
defer later placement geometry. Follow the declared interface contracts.

After reading the required guide and index:
- Read further experience only to resolve the current blocker. Once observations support a feasible action, act.
- Check actual action feedback. If progress stalls, re-observe and change the approach; do not repeat ineffective adjustments. Distinguish holding, placing, and task success.
- Reuse valid localization while the relevant scene is unchanged. Match camera, resolution, and observation step; follow exact tool arguments. A surface point is not automatically a grasp or placement pose.
