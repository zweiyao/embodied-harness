# Bounded UniVTAC tool pilot

This protocol records at most 40 simulator attempts and 80 offline model
requests. It does not launch a simulator, create a second planner, generate
candidate tools, or claim that an accepted tool improves task success. RPent's
runner supplies the real model sessions, observations and evaluation results.

## Fixed allocation

| Stage | Task and seeds | Model | Attempts |
| --- | --- | --- | ---: |
| Environment/control smoke | `insert_hole`, 0–1 | Script | 2 |
| Exploration | `insert_hole`, 2–3 | GPT-6 Astra | 2 |
| Provisional tool use | `insert_hole`, 2–3 | Qwen3.8 Max | 2 |
| Final interface validation | `insert_hole`, 4–5 | Qwen3.8 Max | 2 |
| Held-out C/D/E/F | `insert_tube`, `pull_out_key`, 100–102 | Qwen3.8 Max | 24 |
| Held-out C/E | `insert_tube`, `pull_out_key`, 100–101 | GPT-6 Astra | 8 |

C supplies RGB-D, tactile observations and fixed manual statistics. D adds G0,
a generated perception tool without Max invocation feedback. E adds G1, made
with Max invocation feedback. F retains C's executable tools and conveys G1's
method as language guidance. F must not advertise an unavailable executable API.
Control behavior and observation availability remain equal across conditions.

The held-out task names do not enter tool development. These small samples
support an exploratory comparison, not broad task or unseen-model generalization.
Max participates in development. This allocation does not measure full-episode
RGB-D versus tactile information gain; that requires a separate experiment.

## Operator interface

Run commands from the remote RPent checkout with its environment activated:

```bash
python -m robots.univtac.pilot /absolute/new/batch init
python -m robots.univtac.pilot /absolute/new/batch manifest
python -m robots.univtac.pilot /absolute/new/batch reserve dev-01 fresh-session-id
python -m robots.univtac.pilot /absolute/new/batch scene ATTEMPT_ID scene.json
python -m robots.univtac.pilot /absolute/new/batch finish ATTEMPT_ID outcome.json
python -m robots.univtac.pilot /absolute/new/batch summary
```

`reserve` must precede simulator startup. A reserved slot is spent even if
startup, networking or execution fails. There is one attempt per cell, no
implicit retries, and one active attempt at a time. An interrupted attempt
remains charged after restart; explicitly finish it as `abnormal_exit`. Model
requests retried offline need a new reservation and count toward 80.

The Python interface is `Pilot.create(root)` / `Pilot(root)`,
`reserve_episode(cell_id, session_id, freeze_id=None, memory_mode="read_only")`,
`record_scene(attempt_id, components)`, and `finish_episode(attempt_id, outcome)`.
The runner must actually create a fresh model conversation and enforce read-only
memory/tool access; the ledger checks distinct session IDs and the declared
memory mode but cannot isolate an external model process.

`components` must contain nonempty `model`, `state`, `physics`, `sensors`, `rng`,
and `assets` entries. These describe the simulator model, full recorded initial
state, physical settings, sensor calibration, random state and asset checksums.
They must not include the tested language model name or wall-clock timestamps.
The adapter verifies any referenced file checksums before calling the ledger.
Same-task/seed held-out attempts must have identical component hashes, including
across language models. A mismatch raises before actions: finish the charged
attempt as `scene_mismatch`. Hash equality only covers recorded components;
soft-body state completeness and reset/restoration fidelity require separate
smoke evidence and must be reported as unverified until measured.

`outcome` contains `termination_reason` and nullable boolean `native_success`.
Supported reasons are `completed`, `failed`, `aborted`, `timeout`,
`network_failure`, `setup_failure`, `scene_mismatch`, `abnormal_exit`, and
`budget_exhausted`. Add remote run/artifact references, action count, returned
usage and timings as available. Completion is not task success. Network failure
remains a distinct outcome, not evidence of a planning failure.

For exploration/provisional attempts, additionally provide `maker_inputs` with
`sensors` and `actions` file paths; Max provisional attempts also need a
`feedback` file. The runner must first export sanitized, sensor-only observations
and separate actions/tool-invocation feedback. Do not point these at an entire
run directory or records containing hidden poses, task labels, reward or official
success. The ledger hashes files and rejects subsequent modifications.

## Development, freezing and leakage boundaries

`maker_inputs("G0", attempt_ids)` exports only sensor/action file references.
`maker_inputs("G1", attempt_ids)` also exports the provisional Max invocation
feedback. Both reject smoke, final-validation and held-out attempts. The caller
must keep the maker's file sandbox restricted to the exported files; path
allowlisting in this ledger is not an operating-system sandbox.

Before each offline call use `reserve_offline(purpose, variant, attempt_ids)`.
For `purpose="maker"`, also supply the shared
`maker_budget={"max_calls": ..., "max_tokens": ...}` and that call's
`max_tokens`. Both branches must have the same limits. Calls and reserved output
token ceilings are charged per branch; failed requests are not refunded. This
ceiling is not a monetary or input-token budget. Use
`finish_offline(request_id, result)` to preserve returned usage/error/evidence.
The overall 80-call cap includes maker and diagnostic calls. Calls made outside
these hooks are not accounted for and invalidate the reported budget.

`freeze(bundle)` is allowed after all first six development attempts are
recorded. It requires all four exploration/provisional sensor/action inputs,
recorded G0/G1 maker results using that shared input set, and validation evidence.
The self-contained bundle contains:

- `conditions`: exactly C/D/E/F, each with `tools`, `guidance`, and `parameters`;
  every tool includes `name`, `description`, `parameters`, and full `source`.
- `controller`, `models`, `memory`, and `code_revision`: exact shared control,
  model settings, read-only memory text, and code identification/snapshot evidence.
- `base_tool`, `maker_budget`, `maker_input_attempts`, and
  `validation_evidence`: common starting program, identical branch budget,
  ordered four development attempt IDs, and actual parameter/replay results.

C's tools must be retained unchanged in D/E; F must have exactly C's tools.
The bundle's content hash is the freeze ID. Its file is rechecked before final
validation and held-out reservations; edits invalidate it. Both final Max
validations must use this freeze and record `interface_validation_passed: true`
before formal reservations are accepted. This flag means interface acceptance,
not improved task success. The runner supplies the evidence; the ledger does
not invent or independently infer the flag from prose.

After freezing, offline development is closed. A changed tool, parameter,
controller or guidance needs a new, separately budgeted batch; do not change the
frozen file or reinterpret failed held-out runs as development data. The runner
must execute the frozen source and tool declarations rather than mutable library
entries. Runtime data belong outside Git.

`summary()` reports every charged attempt, its recorded initial fingerprint,
freeze ID, termination and native outcome. Compare matched task/seed rows and
report missing/infrastructure outcomes explicitly. Record actual new-tool use;
a success without its invocation does not demonstrate benefit from its code.
