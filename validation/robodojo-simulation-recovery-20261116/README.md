# Recoverable RoboDojo EEF range rejection

A target outside the existing 0.05 m / 0.35 rad decision bounds is a recoverable
rejection, distinct from a transport or physics failure. The rejected native
step executes nothing. The outer `move_eef` cancels remaining controls, preserves
all successful ACKs, reports `steps_used`, `cancelled_steps`, `rejection` and
`replan_required`, and returns the normal fresh images/state. The model then
chooses its next action in the same episode; no hidden retry or reset occurs.

Entry validation uses the same recoverable result with zero executed controls.
Only the dedicated `EefTargetLimitError` takes this path. Malformed inputs,
transport/physics failures and cancellation retain their existing handling.
Decision limits, local IK task increments and joint limits are unchanged.

RoboDojo owns a concise simulation recovery prompt. Other integrations retain
the shared uncertain-execution stop policy; the shared instruction moved into
its own Markdown source so the simulation choice cannot weaken physical-robot
rules. Frozen LIBERO materials are unchanged.

Remote Python 3.11 checks: **2152 passed, 16 skipped**; full pre-commit and strict
EN/ZH Sphinx passed. All 21 Markdown resources in the wheel match source.
Regression cases cover zero-action rejection on either bound, a rejected
mid-chunk preserving two ACKs and cancelling three steps, continuation with a
fresh observation, and a genuine physics error remaining an error. The tool
parameter schema is unchanged; only its updated recovery description was
changed in the contract fixture.

The previous task-0 episode and incident classification remain intact. A new
single task-0 repeat is recorded separately; unit checks do not establish its
task outcome or a success-rate improvement.

Upstream reference: [GPT-as-Policy GPT-only workflow](https://github.com/anonymous-report-421/GPT-as-Policy/blob/8f3d362b077d8efb77e2a7274d5b2c20e2243846/hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md#L57)
distinguishes validation rejections from transport/physics errors. This change
implements that distinction for RPent's multi-step EEF call.
