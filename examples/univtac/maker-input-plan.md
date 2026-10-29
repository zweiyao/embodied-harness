# Common G0/G1 maker input plan

The initial controlled driver is `robots.univtac.pilot.maker`. Each branch starts
from the same empty skeleton, without the hand-authored prototype or this
conversation. Its original common-input contract and historical requests remain
immutable. The separate `robots.univtac.pilot.maker_revision` driver supports one
paired refinement using each branch's own successful initial candidate.

## Shared observations

Obtain development file references through `Pilot.maker_inputs(variant,
attempts)`. Both branches use the same ordered development attempts and exactly
the same deterministic summary of their `sensors.zip` and `actions.json`.
Record the source hashes, summary hash, serializer version and image ordering.
Do not discover files by traversing the surrounding run directory.

Reuse `robots.univtac.pilot.replay.load_frames` to decode the sensor allowlist.
Read the ZIP manifest for step indices, select four evenly spaced recorded
steps including first and last, and select the newest frame from each decoded
window. For each selected step supply the original head/wrist and bilateral
tactile RGB images, labelled by attempt, step, camera/finger and resolution.
Convert tactile float RGB to PNG using the already documented display-only
round/clip conversion; numeric arrays retain their original values.

The compact numeric summary contains:

- All recorded hand poses and action targets, with coordinate units, command
  step, execution receipts and actual hand translation/rotation differences.
- For selected frames, camera calibration, finite-depth fraction and a fixed
  regular depth grid. Nonfinite samples are explicit nulls, not zeros.
- For each selected tactile frame, reference kind, image/depth units, finite
  fractions, depth quantiles, and the full reference/current marker coordinates
  (64 rows in the current sensor). Preserve per-frame rows; do not assume row
  identity across time. These are observations, not force estimates.
- Shapes and missing-field indicators for the complete input contract, so the
  generated program can operate on full arrays even though the prompt uses a
  deterministic numeric summary.

No success labels, evaluator target poses, object poses, inferred official geometry,
expert actions, evaluator files, audit reports, old conversational conclusions
or existing candidate output are inputs. Do not rank or select frames using an
outcome. Keep task wording and the sensor/tool API contract separate, identical
between branches, and frozen before dispatch.

G1 alone may receive the separately authorized Max `feedback.json` files that
`Pilot.maker_inputs` returns. Those remain a distinct additional field and are
not used to select or modify the shared observation summary. G0 receives no
such feedback field. This defines the initial-stage feedback difference.

## Minimal SDK driver

The maker drivers reuse
`robots.libero.research.codex_sdk.complete_recorded` for a fresh remote Codex SDK turn.
That helper already uses an ephemeral thread, isolated home/work directory,
disabled tools and no MCP. Use a UniVTAC-specific input contract, not the
LIBERO `TEACHER_PROMPT`, whose camera/state fields differ.

The initial driver performs these steps:

1. Validate and hash the shared input bundle; write the exact request, image
   identities, model profile and shared output budget before dispatch.
2. Charge `Pilot.reserve_offline("maker", variant, attempts, ...)` once before
   each real request. Retries consume requests and both branches share the same
   maker budget.
3. Use the server-owned GPT profile/credentials and remote proxy configuration;
   request a standard `{name, description, parameters, source}` declaration.
   Do not supply the manually assisted prototype or previous conversation.
4. Save the returned text and usage. Validate declarations without importing
   generated code. Replay remains a separate operation using the existing Docker
   sandbox; record execution errors without silently rewriting the tool.
5. Call `Pilot.finish_offline` with the response/replay artifact references,
   hashes, available usage and any error. Publishing/freezing remains separate.

Both stages retain the original maker settings: GPT-6-astra, low effort,
180-second SDK-turn limit, at most two calls and 16,384 returned output tokens per
branch, and 8,192 output tokens per call. The SDK has no hard output-token cap;
the prompt limit plus returned-usage check is explicitly
`soft_limit_and_posthoc_check`. Missing or excessive usage rejects the result.
Failures still consume calls. The 300-second consumer/experiment timeout does
not change maker settings. Only SDK events and reasoning actually returned by
the service are recorded.

## Paired refinement contract v2

`maker_revision.prepare(pilot_root, windows)` validates two development windows,
then writes content-addressed feedback, contract and G0/G1 request files. It does
not reserve a request or invoke a model. Each window names `attempt_id`, `first`
and `after` response directories; only `dev-03` and `dev-04` are accepted. The
first request must be a completed `tool_acceptance` ledger entry, the continuation
a completed `after_native_observation` entry for the same input. Recorded request
wire hashes, exposed G1 declaration and all first-call/return pairs are checked.

The common sensor/action payload, original `common_hash` and image pixels remain
unchanged. Both refinement requests additionally contain exactly the same
`shared_observed_measurements`: successful native perception arguments/results
from these Max queries, with recorded frame, camera, units and calibration fields
retained. Measurements are deduplicated and sorted by content hash, without
acquisition order, tool-call IDs, model reasoning, errors or usage. No missing
frame/time/coordinate field is inferred. Image references contain verified hashes,
not new image pixels or base64 text.

This supplement equalizes the additional measured values: native depth queries
can provide exact pixels absent from the original 8×8 depth summary. It is
explicitly a second-stage input addition from Max-selected queries. The query
arguments still reveal selection cues; sorting does not remove that limitation.

G1 alone also receives the actual returned messages, calls and tool returns in
order, plus its original development feedback. A first response with no tool
returns is labelled `tool_results_seen_by_model=false`; the continuation is true
only after all returned observations are present. Returned thinking is a model
claim, length-limited output is incomplete, and action proposals remain
unexecuted. Review reports, evaluator data, success labels and heldout records
are not read. Binary image artifacts are checked and replaced with references.

The two branches receive their own initial candidates, so this is paired
refinement, not a new comparison from an identical candidate. `run(pilot_root,
binding)` revalidates immutable inputs, charges the remaining original maker call,
and records the exact prompt, images, events, response, usage and candidate. It
does not replay or publish. Both branches must reference the same revision
contract. Freezing requires successful posthoc-budget checks, available usage,
and exact agreement between each final generated tool and its recorded candidate.
Original contracts, source files and ledger events are never rewritten.
