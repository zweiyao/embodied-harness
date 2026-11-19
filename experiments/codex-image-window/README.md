# Codex request image window

This experiment applies to the native Codex client at OpenAI commit
`092d3acd6bec3e3a14bdc7e7a2810ab628ab759d` (CLI version 0.162.1).
Apply the patch in a separate checkout of that commit.

```sh
git apply --check /path/to/window.patch
git apply /path/to/window.patch
cd codex-rs
# The release tag stamps Cargo.toml but leaves 161 workspace crate versions at 0.0.0 in Cargo.lock.
# Align only these local versions before using --locked. External packages retain their pins.
python3 - <<'PYLOCK'
from pathlib import Path
import re

lock = Path("Cargo.lock")
old = lock.read_text()
blocks = old.split("[[package]]")
changed = 0
for i, block in enumerate(blocks):
    if '\nsource = ' not in block:
        blocks[i], count = re.subn(r'(?m)^version = "0\.0\.0"$', 'version = "0.162.1"', block)
        changed += count
assert changed in (0, 161), changed
lock.write_text("[[package]]".join(blocks))
PYLOCK
cargo build --locked --profile dev-small -p codex-cli --bin codex
cargo test --locked --profile dev-small -p codex-core --lib window_preserves_the_original_prompt_and_mixed_tool_outputs
```

The candidate replaces each older typed image block with `[Earlier image omitted]`
in the outbound copy of the prompt. The ten most recent image blocks share one
window across user messages and function and custom-tool results. A tool that
returns three camera views occupies three slots. Plain text and opaque encrypted
items pass through as supplied. A WebSocket continuation can reuse an earlier
response only while its input prefix matches. Moving the window can require
sending the full filtered input again.

Use the pinned Python SDK and matching code-mode helper from the stock installation.
Place the candidate executable in the same package layout in a private directory,
with the stock helper beside it and the matching resource directories available.
Pass each binary by absolute path. Run the probes in the RPent Python environment.
The mock provider and synthetic camera server bind to loopback. The camera fixture
runs the RPent MCP adapter and returns numbered 640 × 480 PNGs.

```sh
python verify_wire.py /path/to/stock/bin/codex ws stock --source mcp
python verify_wire.py /path/to/candidate/bin/codex ws window --source mcp
```

Repeat with transports `http` and `ws` and each image source `user`, `mcp`,
`view`, and `code`. Three further cases use the default user inputs with
`fallback`, `retry`, and `http --compact` (place `--compact` after the mode).
They exercise a rejected WebSocket upgrade, a retried HTTP 503, and the native
remote-compaction request. The probe reconstructs the server's input from
`previous_response_id` and decodes image identifiers from pixels. It also reads
back the twelve user images from thread history. An assertion failure exits
nonzero.

These fixtures measure request contents. Evaluate task success, elapsed time,
input tokens and cached input tokens in a separate paired RoboDojo experiment.

## RoboDojo paired pilot

Both builds used Astra/high, a single thread, layout 0, the same memory and EEF
tools, 200 model interactions and a 3,600 s planner budget. Wall time includes
environment initialization. Total tokens are reported input plus output; cached
input is included once.

| Task | Client | Native result | Responses | Total tokens | Uncached input | Wall time (s) |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 6 · cover_blocks | Control | Success | 85 | 7,833,751 | 160,392 | 921.9 |
| 6 · cover_blocks | Ten images | Success | 80 | 4,014,881 | 2,934,609 | 1,043.1 |
| 7 · deposit_coin | Control, repeat | Failed at interaction limit | 200 | 21,966,679 | 329,162 | 3,166.1 |
| 7 · deposit_coin | Ten images | Failed at time limit | 177 | 16,020,431 | 12,512,230 | 3,648.3 |

Task 7's first control run was excluded after five WebSocket reconnects. The
replacement recovered from one reconnect late in the episode. Its full duration
includes that interruption. Both tasks have uninterrupted first-50-response
comparisons. Across those 50 responses, the control and candidate took 494.1
and 629.7 s on task 6, and 671.5 and 1,192.9 s on task 7. These are durations
from planner request to the 50th usage update; robot trajectories can diverge.

The smaller window reduced reported total tokens on these two runs. The share
of input served from cache fell from 98.0% to 26.8% on task 6 and from 98.5% to
21.7% on task 7. Both candidates took longer. Each task has one observed pair.
Per-run identifiers, first-action times and the matched-prefix usage breakdown
are in [the pilot data](paired-pilot.json).
