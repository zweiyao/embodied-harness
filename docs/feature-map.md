# RPent application feature map

The `rpent` CLI starts a Python FastAPI/Uvicorn dashboard. The server serves HTML and JavaScript ES modules directly from `rpent/dashboard/`. A normal simulation launch uses `rpent --robot libero --dashboard` with that environment’s dependencies and configuration. Use the isolated [verify-app workflow](../.agents/skills/verify-app/SKILL.md) for verification. Its pytest fixtures start the real HTTP server on a temporary loopback port with a synthetic LIBERO workbench, two sample task choices and one recorded episode. They create no planner, simulator or robot session.

## Browser journeys

Run selectors with `python -m pytest tests/e2e_tests/dashboard -k SELECTOR`. The setup page requires a configured setup profile. With no setup profile, the root serves the console.

| Feature and entry | User actions | Expected evidence | Browser selector |
| --- | --- | --- | --- |
| Task setup, `/` | Wait for ready, select task B and seed 3 in the demo suite | Preview updates to `/rpent-task demo 1 3`. Enter remains disabled until the fixture model passes its connection check | `setup_preview` |
| Tool library, `/tools` | Open details for `move_to`, inspect the parameter section, close | Dialog identifies the selected tool and shows its parameter heading. The catalog remains available after close | `tool_details` |
| History and replay, `/runs` → `/runs?id=<id>` | Expand the sample task folder, open its record, select the initial step | The task folder shows one successful run and its instruction. Detail shows the recorded native success, last action and the initial state after selecting step 0 | `run_replay` |
| Live monitor, `/console` | Open the idle session and wait for the first server-sent state event | Live indicator appears, run identity shows no experiment and abort is disabled | `console_stream` |

## Additional interaction surfaces

| Feature and entry | Action in a disposable fixture | Expected result | Existing verification |
| --- | --- | --- | --- |
| Next-run setup, `/` and `/api/session/config` | Select an available tool, attempt an unknown tool, inspect a previously claimed task | The server validates selections and freezes each claimed task’s configuration | [Workbench contracts](../tests/unit_tests/rpent/dashboard/test_workbench.py) |
| RoboDojo native task picker, `/` | Select a task and layout in a RoboDojo fixture, submit an invalid layout to the test server | Task and layout populate the command. Unsupported layouts are rejected | [Picker JavaScript](../tests/unit_tests/rpent/dashboard/test_task_picker_ui.py) and [RoboDojo contracts](../tests/unit_tests/robots/robodojo/test_workbench_contracts.py) |
| Control input, `/console` | Submit or interrupt using simulated interaction state | Queued messages and task replacement follow the recorded session state | [Planner controls](../tests/unit_tests/rpent/dashboard/test_planner_control_contracts.py) and [session contracts](../tests/unit_tests/rpent/dashboard/test_session_contracts.py) |
| Results and metrics, `/console` and `/runs` | Present success, failure and unknown outcomes using test records | Badge follows the environment verdict. Reported token usage preserves cache accounting | [Result badge](../tests/unit_tests/rpent/dashboard/test_result_badge_ui.py) and [metrics](../tests/unit_tests/rpent/dashboard/test_run_metrics_ui.py) |
| Flexiv operator UI, `/` and `/api/flexiv/status` | Inspect simulated readiness and control gating with the mocked backend | UI reflects operator status and gates commands accordingly | [Operator UI contracts](../tests/unit_tests/robots/flexiv/test_operator_ui.py) |
| CLI dashboard launcher, `rpent --dashboard` | Exercise argument parsing and session dispatch through the CLI tests | Selected planner and dashboard options reach the session runner | [CLI tests](../tests/unit_tests/rpent/cli/test_main_contracts.py) and [dashboard dispatch](../tests/unit_tests/rpent/cli/test_dashboard_contracts.py) |

Node-backed pytest cases exercise JavaScript logic. Install Node in the test environment for those cases and inspect pytest’s skip count. Use a separate, explicitly scoped integration run for a real model request, video playback with a real codec, or a simulation rollout. Keep real robot actions outside the automated UI workflow.
