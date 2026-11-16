# Flexiv layered prompts and native analysis deployment

The physical Flexiv workbench now uses the shared prompt renderer and native
Codex calculation, code execution, image viewing, cropping and episode notes.
It runs Astra/high with explicit `--codex-analysis --codex-full-access`. The
existing 25-response and 3,600-second budgets remain unchanged.

Prompts compose shared requirements, the single-arm Flexiv RDK contract, the
operator's task and an indexed experience pointer. Positions remain native TCP
in robot-base metres; rotations retain the existing RDK formats. Neither the
RoboDojo dual-arm link6 contract nor its simulation recovery policy is applied
to physical hardware. Experience bodies are not injected into the system prompt.

Only the dashboard service's working directory and launcher are overridden.
Its new source is the isolated `prompt-system-refactor-20261116` checkout.
Existing RDK, ENV and calibrated RGB-D services retain their original
`/home/zwy/work/harnessvla` implementation. Control files, device parameters,
calibration and three experience files were verified unchanged. Independent
changes in the original checkout were not overwritten.

After the operator confirmed stopping, the handoff checked idle recording, no
operator lease, unarmed control and stationary measured joints. It stopped the
collector and started the existing physical services and new dashboard. Normal
collector shutdown may issue its existing Stop; no enable, reset, motion or
gripper command was requested. The deployed robot was IDLE, unarmed and without
fault. No model task was started. RDK audit events since the saved handoff time
contain zero new control commands.

The two calibrated RGB-D views returned real 1280×720 images through the new
client and unchanged ENV. A no-robot Astra/high probe verified four native
commands with exit code zero, two native image views, geometric error
calculation, a pixel-checked crop and the explicit full-access permission mode.
The deployed workbench's separate model connection check also passed. Remote
Python 3.11 unit tests: **2152 passed, 16 skipped**; pre-commit passed.

Full native filesystem/network access is explicit: source, evidence and memory
read-only instructions are task rules, not OS isolation. RPent file-tool write
authorization and physical operator gates remain in place. The Xense device is
currently absent, so tactile operation is not claimed. No physical task success
or performance improvement was tested.

On the remote desktop, open <http://127.0.0.1:8083/>. The existing LAN access
configuration, proxies and Mac network were not changed. RoboDojo, LIBERO and
UniVTAC process IDs remained unchanged. The old collector is stopped while
RPent owns the physical resources.

Deployment artifacts are under
`/home/zwy/work/embodied_harness/validation/flexiv-layered-analysis-20261116/`:
`preservation.json`, `prompt-preview/prompt-sources.json`,
`analysis-probe-service.json`, `native-tool-verification.json`, `handoff.json`,
`deployment.json`, `unit.log`, `pre-commit.log` and the original diagnostic logs.
Initial helper/network/readiness failures were retained; final checks used the
service environment and an audit window beginning at the recorded handoff.
The launcher and systemd drop-in are included here as deployment evidence;
private workbench profiles and credentials are not included.

To restore the old prompt launcher, first end any task and have the operator
stop the robot and disarm control. Remove only
`~/.config/systemd/user/harnessvla-flexiv-dashboard.service.d/zz-layered-analysis.conf`
and reload systemd. The original launcher and resolved service backup remain
available. Switching back to collector mode additionally requires releasing the
RPent hardware services; it must not interrupt an active operator.
