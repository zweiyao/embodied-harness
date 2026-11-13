# README hardware and UniVTAC results

The maintainer requested both method/RPent hardware results and UniVTAC results
on the holmes_RUA GitHub landing page. This is a follow-up on docs/robot-results after homepage PR #8 merged.
English and Chinese are updated together; the runtime, tools, memories and active
LIBERO experiment are unchanged.

- real-robot.json transcribes all nine rows of the supplied image. The maintainer
  explicitly confirmed Token/time are per-run means. Each task/method has five
  runs. Model, budgets and raw hardware run IDs were not supplied; no independent
  hardware-log audit is claimed. The original baseline label is retained and
  the three-round optimized method is labeled holmes_RUA.
- univtac.json recomputes the three archived 10-run cohorts from the actual
  remote result files: initial native baseline, native repeat and frozen tool.
  It retains both native groups, the per-task outcome changes and the frozen
  d6c13e92 tool identity. Development-task trials are excluded. Token totals mean
  input plus output without double-counting cached input. Authoring costs are
  excluded and the small sample does not establish a causal success-rate gain.
- checks.json records source hashes, arithmetic, links and GitHub Markdown
  rendering. Both existing LIBERO table sets retain all 33 numeric rows exactly.

Only standalone Markdown and compact result metadata change. Sphinx and harness
unit tests are not rerun because their sources/build inputs do not change.
No model requests, simulator/robot experiments, deployments or service restarts
are part of this documentation update. Source tables remain archived; the
screenshot and raw observations/videos/weights/credentials are not committed.
