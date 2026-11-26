# Benchmark experience libraries

Maintain reviewed experience under `memory/<benchmark>/`. Each benchmark has
its own `MEMORY.md`, with relative links to experiment-derived notes. Add
`global/`, `task-family/` or `task-specific/` when publishing notes for that
scope. Global notes apply across tasks within their benchmark. Record task and
tool applicability, failure conditions, source run IDs and verification status
in each note. Review transfers before registering them in another benchmark.

Publish the same tree to the deployment's `RPENT_MEMORY_ROOT`. Without that
setting RPent uses the checkout's `memory/`. An explicit `--memory-dir` can pin
a corpus for a reproducible run. RoboDojo and Flexiv use their local benchmark
libraries in the shared deployment. LIBERO evaluation retains its model-based
Hugging Face selection and caches the version under `libero/.versions/`. When
the workbench selects the existing prose guidance package, it retains the
frozen prompt files and reads experience from the centralized LIBERO index.
UniVTAC continues to use a per-run `empty-memory/` directory.

The run's `prompt-sources.json` records the resolved memory root and index
digest, plus the selected upstream version when applicable. In a centralized
deployment, the native file tools for these four benchmarks use the resolved
current library and the episode's output directory. A full-access command
runner uses the host account's permissions.

The previous `language-materials/v1/memory` export is historical LIBERO material.
Its run records, prior corpora and historical checkouts remain available for
reproduction. Route reviewed entries to this tree through the normal approval
process. See the [migration inventory](migration.json) for the initial sources.

`rpent-memory --memory-dir PATH validate` checks supported RPent note metadata.
Update the index when publishing a reviewed leaf. The generated index command
covers entries with parseable frontmatter in `global/` and `task-family/`.
Preserve hand-maintained links and any task-specific entries on regeneration.
