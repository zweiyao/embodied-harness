# W2 material validation

The approved 96-word user prompt was published as the independent read-only
package `qwen-decision-w2-381e10402bd1` under the remote project's
`language-materials/` directory. The parent remains
`qwen-evidence-v3-readable` (`qwen-evidence-v3-c6c7f677d400`). W2 is not selected
by any default and this build started no policy or simulator.

Only `user.md` content changed. The manifest changes are exactly its version
and `files.user.md`; all other package bytes and the original parent remain
unchanged. The new user SHA256 is
`c2fcb0c20b6df26c943a04377b9ed064897783fe2559dcc7cab716046bddffe8`.
Published files have mode 0444 and directories 0555. This is a read-only
published package, not a claim that its owner cannot deliberately replace it.

Remote validation used the real frozen R `freeze_materials` and robot prompt
renderer for parent and W2 at tasks 4 and 0, seed 0. All four frozen copies
match their manifests; all substitutions resolve. The rendered systems are
identical after normalizing only each run-directory path. The 785-word guide,
MEMORY index, three experience bodies, and system prose were not rewritten.
The 303 source hashes, native catalog, six default prompt renders and selected
18 tool identities remain unchanged.

The existing language-material unit tests passed: **4 passed in 0.02 s**.
Scoped Ruff check/format and local diff whitespace checks passed. The initial
builder lint found E731 in its local path-normalization helper; replacing the
lambda with an equivalent function and formatting did not change material
bytes. `execution-provenance.json` records both script hashes and the retained
exact executed script. The unchanged production full suite was not rerun.

`material-handoff.json` supplies the exact package/source paths and hashes.
`validation.json`, `material-manifest.json`, `parent-files.json`, and the two
`rendered-*-t0-user.md` files provide compact review evidence. Full freeze,
default-render and catalog snapshots remain in the remote validation directory
and the workspace debug archive; no raw observations or credentials were used.

This validates isolation and prompt assembly only. NEXT/NEED compliance,
startup batching, grasp decisions, task success and comparative efficacy are
unmeasured until the separately gated screen. The prompt adds no detector,
automatic action, retry, policy agent, or success rule.
