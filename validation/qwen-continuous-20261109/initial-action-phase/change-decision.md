# A: initial language-action phase

Recorded before implementation under the user's explicit continuous, unattended
LIBERO optimization authorization. The exact five-production-file draft is
initial-action-phase.patch.draft; base-hashes.json identifies its parent bytes.
Parent is V from09. Original/main workbenches, all failures and C are preserved.

## Evidence and hypothesis

09 task0/4 spent10/13 tool calls and228/213seconds before the first action. Each
made six geometry queries before a Pi0 pickup that takes language, not queried
coordinates. Reading the next-action experience did not enforce its principle.
A phase boundary should remove that particular premature work and leave more
budget for recovery and the second object. It may instead trigger other wasted
reads, premature action or finish; those remain valid model failures.

This is a workflow intervention, not proof of a reusable perception program's
benefit. It does not fix failed contact recovery, semantic identity errors or
accumulated image-history costs. No transport investigation is included.

## Concrete change

- `robots/libero/research/manual.py`: `initial_action_phase=False` by default.
  When enabled, initial exposure is the intersection of the frozen selection and
  finish/list_dir/read_text_file/write_text_file/view_env_state/read_image/
  segment/pi0_pick/pi0_doubled. Other selected tools become available after a
  language primitive returns a new recorded step with chunks_used greater than
  zero, whether its pickup heuristic succeeds or fails. Invalid arguments,
  readonly observations and zero-chunk calls do not unlock it. Direct hidden-tool
  dispatch returns an explicit error without invoking its handler. Journal the
  phase transition. No automatic action, target choice, chunk-limit change,
  release or reset. Native tools and schemas are unchanged.
- `rpent/planner/api_loop.py`: existing FunctionToolset prepares declarations
  per request. An optional toolkit availability predicate filters that set;
  dispatch rechecks it. No robot-specific names enter this module. Toolkits
  without the predicate preserve the old path. SDK scheduling, finish, timeout,
  cancellation and request limits stay intact.
- `rpent/dashboard/workbench.py`: server-owned boolean, LIBERO/API only, requires
  a selected language primitive; task requests cannot inject it. Freeze into
  the existing prepared task. Default false does not add a request field.
- `rpent/cli/dashboard.py` and `robots/libero/robot_spec.py`: pass the claimed
  frozen flag to ManualToolkit and its selection prompt, not mutable config.

Exact added selection-prompt text (candidate only):

> Initially, inspect identity and choose an enabled language primitive; finish
> if no suitable action is justified. Geometry and manual tools become available
> after its first recorded action feedback, including failed pickup. Sample
> geometry when the next manual action needs it.

No new experience or W2 text, image contract, controller, proxy, model or budget
change. Generic file-tool permissions and on-demand memory remain unchanged.
The first screen is limited to the same two pick/place tasks0/4. This boundary
assumes an available language primitive can reasonably begin the task; it is
not a universal robotics rule. Before ten-task coverage, verify suitability on
other task families without introducing fixed task trajectories. Coverage still
requires one frozen candidate, not a union of versions.

## Validation and decision

Create a fresh remote candidate from V after verifying its full source handoff.
Preserve parent supporting examples/tests/memory fixtures and independent files.
Add tests to existing manual/API/workbench suites: default parity; actual SDK
first/next-request tool sets; blocked-tool retry cannot dispatch; successful and
failed nonzero-chunk action unlock; readonly/zero-chunk/invalid calls do not;
finish remains possible while locked; wrong types, missing primitive, non-LIBERO,
non-API and request injection rejected; claimed flag survives config changes.
Exercise actual ManualToolkit action feedback rather than a success boolean.
Run focused tests, scoped hooks and full offline units remotely. Full historical
hook failures remain reported separately; no unrelated formatting edits.

After software validation, freeze source and prepare two fresh task0/4 seed0
cells, two environments, Flash nonthinking,600s/30requests/16384, remote direct.
Record actual per-request tool exposure, phase transition, first-action time,
VLA chunk use, geometry-query count, second-object progress and official success.
Existing09 failures remain unchanged. Geometry reduction alone is not efficacy:
promote only on success-first evidence, then broaden frozen development coverage
and finally fresh independent50+50. No policy experiment starts before its
specific runner/preflight plan and verification.

Draft review before implementation corrected a nonexistent ToolResult.error
helper to the established error payload and added nonzero recorded chunks to
avoid unlocking on an action call that executed no chunk. No deployed code was
changed during that review.
