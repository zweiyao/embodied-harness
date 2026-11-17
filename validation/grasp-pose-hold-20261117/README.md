# Hold the grasping arm during closure

The approved revision adds two short instructions:

- `rpent/prompt/common.md`: for pick-and-carry grasps, keep the grasping arm
  at its grasp pose during closure and avoid combining closure with that arm's
  lift or transport.
- `robots/robodojo/prompts/control_eef.md`: keep the grasping arm's EEF pose
  fixed when closing to grasp.

Only the grasping arm is constrained. The earlier draft's settling checks,
verification lift and follow/no-slip transport procedure were not introduced.
No tools, controllers, limits, coordinates, experience leaves or legacy language
materials changed.

Remote Python 3.11 validation:

- Prompt composition/provenance, RoboDojo EEF and Flexiv contracts: 64 passed.
- Full unit suite: 2161 passed / 11 skipped in 75.11 seconds.
- All-files pre-commit: passed.
- With current live tool selections, candidate and deployed prompt renderings
  contain each applicable new rule once and record matching source hashes.

Only the two Markdown files were copied to the active layered checkout after
checking their original hashes and preserving backups. RoboDojo and Flexiv read
these files when constructing new TaskRun prompts. Six workbench PIDs and the
four affected workbenches' settings are unchanged; no restart, task, model API
request or robot action was issued. Existing conversations are unchanged.

The initial standalone rendering probe picked up the older editable environment
and failed to import prompt composition; it was rerun with explicit source
PYTHONPATH. The unit suite used the isolated checkout throughout. Detailed logs,
render checks, deployment hashes and backups remain outside Git at
`/home/zwy/work/embodied_harness/validation/grasp-pose-hold-20261117/`.
No Sphinx input changed. Actual grasp/drop-rate benefit has not been tested.
