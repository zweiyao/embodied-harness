# RoboDojo RPent v1 memory access

Approved proposal: `proposals/robodojo-rpent-memory-20261114` in the parent
workspace; explicit user approval: “批准”. Deployed code is `f09ce22` in an
independent checkout. The older runtime remains preserved.

RoboDojo now uses the same frozen `language-c592f23a3a324c08` memory corpus as the
completed LIBERO Object-T final50 batch, through `--memory-profile local` and an
explicit `--memory-dir`. No experience body or index was rewritten. A 38-word
reference in the dev user prompt directs the planner to inspect the scene, read
the index and relevant leaves, check robot/tool/scene assumptions, derive current
geometry and record consulted files. Experience bodies are not injected into the
system prompt. The corpus contains historical LIBERO lessons; its “global” layer
does not establish applicability to every robot. Stored action values must not
be replayed as RoboDojo commands. Flash eval-fair discovery behavior is unchanged.

Validation:

- 160 focused tests pass; 152 Flash/runtime regressions pass after supplying one
  old fixture's missing memory_dir input. All original assertions are retained.
  The initial full-suite failure is preserved remotely.
- Full Python 3.11 suite: 2091 passed / 16 skipped in 69.73 seconds. All-files
  pre-commit and the functional commit-message check pass.
- English and Chinese Sphinx builds pass with -E -W --keep-going; the rendered
  memory paragraph is present in both languages.
- The actual file tools read the frozen index and an existing leaf in an offline
  toolkit with an ENV substitute. Published writes are denied; another robot's
  existing repository memory file is rejected with PermissionError. No simulator,
  physical robot or policy task is run by these checks.
- All 216 protected material files and 1632 protected old-runtime files retain
  their hashes. Twenty-four historical run metadata files are unchanged.
- Live service uses the new source and memory paths; current model, 12 tools,
  120 interactions, 16384-token setting, 600-second planner budget and unlimited
  dev-action diagnostic mode are preserved. Model text connectivity passes in
  11.776 seconds. Workbench is ready with no current task; Mac homepage returns200.

[summary.json](summary.json) records the configuration and preservation checks;
[memory-smoke.json](memory-smoke.json) records reads and permission checks;
[authorization.json](authorization.json) records approval and the necessary
fixture correction. Full logs and private backups remain in the corresponding
remote validation directory. No credentials, videos, raw observations or weights
are committed.

These checks establish access and prompt wiring. They do not show that a model
consulted or benefited from memory in a task. No new experiment was started, no
network settings changed, and the previously audited move_to defects are not
modified by this change.
