# Common G0/G1 maker input plan

This is a proposed bounded generation driver, not an executed maker run.
The current hand-authored prototype and this conversation must not become the
initial prompt for a controlled maker run.

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

No success labels, target poses, object poses, inferred official geometry,
expert actions, evaluator files, audit reports, old conversational conclusions
or existing candidate output are inputs. Do not rank or select frames using an
outcome. Keep task wording and the sensor/tool API contract separate, identical
between branches, and frozen before dispatch.

G1 alone may receive the separately authorized Max `feedback.json` files that
`Pilot.maker_inputs` returns. Those remain a distinct additional field and are
not used to select or modify the shared observation summary. G0 receives no
such feedback field. This preserves the intended single experimental difference.

## Minimal SDK driver

A future `make_tool.py` can reuse
`robots.libero.research.codex_sdk.complete` for a fresh remote Codex SDK turn.
That helper already uses an ephemeral thread, isolated home/work directory,
disabled tools and no MCP. Use a UniVTAC-specific input contract, not the
LIBERO `TEACHER_PROMPT`, whose camera/state fields differ.

The driver should perform these steps:

1. Validate and hash the shared input bundle; write the exact request, image
   identities, model profile and shared output budget before dispatch.
2. Charge `Pilot.reserve_offline("maker", variant, attempts, ...)` once before
   each real request. Retries consume requests and both branches share the same
   maker budget.
3. Use the server-owned GPT profile/credentials and remote proxy configuration;
   request a standard `{name, description, parameters, source}` declaration.
   Do not supply the manually assisted prototype or previous conversation.
4. Save the returned text and usage. Validate declarations without importing
   generated code, then replay using the existing Docker sandbox. Record
   execution errors as errors; do not rewrite the tool silently.
5. Call `Pilot.finish_offline` with the response/replay artifact references,
   hashes, available usage and any error. Publishing/freezing remains separate.

Before using this helper for the controlled comparison, connect the configured
output-token limit to an SDK-supported setting: its current `complete` signature
does not accept a token cap. Merely recording `max_tokens` in the ledger is not
enforcement. Its current timeout is 540 seconds; any changed timeout/model effort
must be identical across G0/G1 and recorded. The driver must not claim SDK events
or internal reasoning that the chosen helper does not return.
