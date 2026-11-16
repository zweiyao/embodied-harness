# Layered prompts and optional Codex analysis

Branch `refactor/prompt-system`, based on `55742f6`. Common requirements,
robot/control-mode contracts, task supplements and optional memory discovery
are separate Markdown inputs. CLI and Dashboard archive rendered inputs and
source hashes. Codex fixed instructions use `developer_instructions`; tasks and
follow-ups remain user input. Frozen LIBERO material packages retain their path.

Remote verification: 2141 unit tests passed, 16 skipped; full pre-commit and
strict EN/ZH Sphinx builds passed. The built wheel contains all 19 new Markdown
resources, byte-identical to source. Existing robot-control code is unchanged.
236 protected original source/configuration/memory files retained their hashes.

An isolated loopback candidate on port 38094 is idle with Astra/high,
`--codex-analysis`, and EEF tool selection. No task or robot action was started.
The public workbench has **not** been replaced.

The real no-action Astra/high probe viewed the synthetic image and called the
registered finish tool. Native execution failed before any command ran:
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. The host's
AppArmor restriction also blocks an independent system Bubblewrap invocation.
Calculation, crop creation, native write isolation and network denial therefore
remain **unverified**. No full-access workaround or global AppArmor change was
applied. The scoped host prerequisite requires separate approval and
administrator access; only then can the probe and idle deployment continue.
See [Codex's Linux sandbox requirements](https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md).

Detailed logs and synthetic probe artifacts remain on the remote host under
`/home/zwy/work/embodied_harness/validation/prompt-system-refactor-20261116/`.
Only this small summary is committed. Development failures are retained there,
including an incompatible Starlette pulled into the isolated candidate while
installing documentation tools; matching the original `0.45.3` restored the test
environment without changing the original environments or project dependencies.
