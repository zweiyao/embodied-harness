# Layered prompts and explicit Codex permissions

Branch `refactor/prompt-system`, based on `55742f6`. Common requirements,
robot/control-mode contracts, task supplements and optional memory discovery
are separate Markdown inputs. CLI and Dashboard archive rendered inputs and
source hashes. Codex uses `developer_instructions` for fixed requirements and
user input for tasks and follow-ups. Frozen LIBERO materials retain their path.

Remote Python 3.11 verification: **2143 passed, 16 skipped**; full pre-commit and
strict EN/ZH Sphinx builds passed. The wheel contains all 19 Markdown resources,
byte-identical to source. 236 original source/configuration/memory files retained
their hashes. Robot-control implementations and experience bodies are unchanged.

Both permission modes were checked with real Astra/high and synthetic evidence,
without constructing a robot or task environment:

- Default restricted analysis computed the expected transform, viewed/cropped
  images, wrote notes, rejected source/evidence/memory writes with `EROFS`,
  rejected network sockets with `EPERM`, and enforced RPent file-tool writes.
- Explicit `--codex-analysis --codex-full-access` executed four native commands
  with exit code zero, wrote outside `agent/`, exchanged ping/pong with a harmless
  local test listener, and viewed a verified 61×61 red-square crop. The request
  uses full access for both thread and turn and approval policy `never`.

Full native access was explicitly requested by the operator. It removes native
filesystem/network isolation; treating source, evidence and published memory as
read-only remains a task rule. RPent file tools retain their `agent/` write
boundary, and robot actions use the selected registered tools.

The remote user's normal and Astra-specific Codex configs now specify
`danger-full-access` and `never`, with private backups. A scoped system Bubblewrap
AppArmor profile was installed with authorization; global AppArmor restrictions
remain enabled. No credentials, raw observations or model weights are committed.

The public RoboDojo workbench at <http://10.162.250.228:8094/> now runs the new
checkout with Astra/high, full native access, and the eight-tool EEF selection.
It is idle with no run or native steps. The existing single-source allowlist
remains in place. The page and historical recording return HTTP 200 and video
Range HTTP 206. Old idle RoboDojo auxiliary services were stopped before replacing
the main backend; original checkouts, service configuration, data and rollback
script are retained. LIBERO and UniVTAC processes and Mac networking are unchanged.
No task experiment or real-robot action was started.

Detailed evidence remains under
`/home/zwy/work/embodied_harness/validation/prompt-system-refactor-20261116/`.
Earlier diagnostics are retained, including the initial sandbox startup failure,
a classifier that omitted read-only-filesystem denials, and a crop filename
assumption. Final host checks verified the actual errno, saved crop and SDK events.
