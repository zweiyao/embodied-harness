# Finish-only API candidate: SDK evidence and validation plan

Read-only evidence collected 2026-11-10 from frozen R source and the installed remote `pydantic-ai-slim 2.53.0` (`pydantic-ai-harness 0.53.0`). No model request, simulator action or production edit was made for this analysis. The exact candidate diff and implementation authorization are recorded separately in this directory. Bootstrap and consistent-view candidates remain separate and unimplemented.

## Confirmed failure path

Iteration07 W2 task0 successfully obtained its three startup inputs. Its second response at `08:08:41.974 UTC` contained only `TextPart`: `NEXT=pi0_pick(prompt="pick up the cream cheese box"); NEED=none`. It had no `ToolCallPart`, and no subsequent tool dispatch occurred. The raw first request allowed text output; `planner_tools_only` restricts adapter-added helpers and does not suppress response text.

In `rpent/planner/api_loop.py`, `_HarnessToolkit.output_types` starts as `[str]` and appends the existing `finish` `ToolOutput`. A plain text response is therefore a valid SDK final output. After `Agent.run` returns it, `_Session._run_conversation` has no `finish_result`, completes the Dashboard turn, then waits on `inbox.get()`. `DashboardPlannerControl.complete` sets the activity to idle. The outer planner timeout continues while awaiting new user input. This explains the observed idle period without inventing a failed tool call or network cause. It does not prove that W2 universally causes text-only termination.

## Minimal candidate and configuration ownership

Set server-owned `api_require_finish: true` only in the selected isolated LIBERO workbench JSON. Absent/false preserves the old behavior. The workbench validates a boolean and rejects an enabled setting for another robot. HTTP task/config payloads cannot override it. `prepare` requires an API model profile, retains the existing required-finish selection check, and freezes `api_require_finish: true` into the prepared task only when enabled.

That claimed task already appears in `manifest.json.task` and `dashboard_config.json.task`. `rpent/cli/dashboard.py` forwards the **claimed value**, not mutable server configuration, into `build_planner`; `rpent/planner/base.py` rejects an enabled value for other backends and passes it to `ApiAgentLoop`. The API adapter omits the `str` output alternative only when enabled, retaining the same `finish` `ToolOutput` and all function tools. A missing finish declaration produces an explicit startup error instead of an empty output schema. No prompt, memory, tool description/schema, action choice, camera input or controller changes are included.

## Installed SDK semantics

Paths below are relative to `/home/zwy/work/harnessvla/.venv/lib/python3.11/site-packages/pydantic_ai/`.

- `_output.py:460` defines `allows_text` from the presence of a text processor. The tool-only output-schema branch at `605–611` supplies no text processor. `_agent_graph.py:995–1011` copies this into `ModelRequestParameters.allow_text_output`.
- `models/_tool_choice.py:103–105` resolves an unspecified/auto choice to `required` when direct output is disallowed. `models/openai.py:1460–1493` maps this to the provider's tool-choice field while retaining declared function/output tools. No explicit global `tool_choice` override is needed.
- Provider support is conditional: `models/_tool_choice.py:207–231` permits SDK-derived forcing to fall back to auto for unsupported profiles. The current Qwen profile does not explicitly disable forcing for the non-coder Flash name. This is source evidence, **not verification that the live gateway accepts the wire parameter**; use an offline mocked HTTP/client request to verify local mapping first.
- `_agent_graph.py:2314–2318` processes tool calls when present, so intermediate text plus tool calls remains valid. Public text is not removed. Plain string output does not preempt a co-emitted tool call under the existing early-end strategy (`2493–2499`).
- Without tool calls or an allowed text processor, `_agent_graph.py:2333–2348` creates a `RetryPromptPart` and another SDK model-request node. It does not return a successful plain-text final result. This also covers a provider returning text despite requested tool use.

The existing `_HarnessToolkit.finish` handler still calls the selected finish tool, raises `ModelRetry` if `_finish` is absent, and records an accepted result otherwise. Accepted finish still skips sibling actions under `end_strategy="early"`. Existing environment-terminal detection, operator cancellation, replacement and timeout paths remain intact; the flag does not require an extra finish call after an existing terminal stop.

## Budget and accounting

`Agent(retries={"output": max_turns})`, `_Session.limits = UsageLimits(request_limit=max_turns)`, the pre-request budget check and outer `asyncio.wait_for(..., timeout=self.timeout_s)` are unchanged. SDK correction requests use the same cumulative usage and the same wall-clock envelope: no extra allowance beyond 30 requests/600 seconds in the proposed screen. Repeated invalid text should exhaust the ordinary request budget or timeout as a valid failure. An unsupported-provider/configuration error remains an incident under the existing protocol; do not silently disable the candidate and pool that result.

Journal entries remain real `model_request`/`model_response` events and actual toolkit calls. SDK retry prompts are recorded as SDK feedback in subsequent request history, never as model tool calls or executed actions. Report plain-text-only responses, SDK retry requests, resulting real tool requests, idle intervals, usage and official success separately. Removing an idle wait is a mechanism result, not evidence of successful manipulation.

## Falsifiable validation plan

Use remote offline `FunctionModel` and mocked HTTP fixtures in the existing API contract tests, plus workbench/dashboard configuration fixtures. No live API or environment is needed for these software checks.

1. Default compatibility: absent/false preserves prompt bytes, first-request messages/settings/declarations, normal text completion, transcript shape, budgets and non-API behavior. Freeze timestamps/IDs where necessary for exact request comparisons. Existing original/default tests must keep passing.
2. Wire contract: with the candidate enabled, the mocked OpenAIChat request has `allow_text_output=false` locally and expected `tool_choice=required` on the wire for the configured profile. All function tools plus explicit finish remain available; Qwen thinking stays off. No prompt addition or tool-schema change appears.
3. Mixed/text-only responses: text plus a tool call executes that real tool once and preserves text. A text-only response executes no tool, inserts SDK retry feedback, and proceeds to another request without Dashboard idle/inbox waiting. Then a valid finish succeeds. Repeated text-only responses stop at a small configured request budget with no automatic action or success claim.
4. Finish and termination: accepted finish retains its result and skips sibling actions; a refused finish retries using existing feedback and the same budget; persistent refusal exhausts it. Existing solved/truncated detection and cancellation still stop without an extra request/action.
5. Timeout/operator regression: exercise the same timeout, queued-call draining, operator interrupt and task-replacement fixtures with the opt-in. No late action or continuation may escape cancellation. The wall-clock timer must not reset on text correction.
6. Configuration/provenance: reject nonboolean values, client injection, non-LIBERO workbench opt-in, non-API profile/backend and missing finish declaration. Confirm prepared → claimed → factory → adapter mode is frozen; later server-config changes cannot alter a claimed run. Confirm no flag is added to the default task manifest.

After focused checks, run the required shared-source suite and pre-commit remotely. Freeze source hashes and actual request-schema evidence before root authorizes a policy screen. The proposed W2-plus-finish-only task0/4 screen uses iteration07 W2 as a historical parent, so its time/order difference must remain explicit. No bootstrap, view, experience or additional prompt intervention belongs in that screen.

The alternative of one custom continuation after a text final would leave the first request unchanged, but would require another user/harness message plus manual Dashboard completion, history, cancellation and counter handling. It is a larger workflow change with additional prompt text. The existing SDK output contract already addresses this exact transition; the alternative is not part of this candidate.
