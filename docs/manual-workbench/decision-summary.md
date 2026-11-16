# Post-task decision review

An independent review agent reads a finalized workbench task and writes a JSON
report and a Chinese Markdown report, one entry per high-level action tool call.
It does not join the planner loop, execute actions, write memory, or change the
environment verdict. Model access uses an isolated Codex home and disables MCP,
shell, browser, and other built-in tools.

```bash
python -m rpent.evaluation.decision_summary /path/to/finalized/task \
  --output /path/to/separate/review --model gpt-6-astra
```

Use the same remote model credentials and explicitly selected network as the
experiment. The command inherits networking. It does not start a simulator.

Each request receives only the journal prefix preceding that action, plus up to
three RGB views from the latest completed observation/action response. Long
tool responses are visibly truncated. The model separates observed evidence,
visible planner statements, explicitly stated tool-choice reasons, retrospective
inferences, and unknowns. Claims cite journal line IDs (`E<number>`); planner
attributions must cite visible planner text. Subsequent feedback is paired by
`call_id` and attached by the program after the model request, so future results
are not evidence for earlier decisions.

The JSON preserves source hashes, action arguments, cited evidence, feedback,
and separate reviewer token/time counters. Existing action reports are reused
only when source hashes, action identity, model, prompt and evidence request match. Review failure is separate
from experiment success. Reports remain runtime artifacts, not agent memory or
public Git content. Full videos, all intermediate frames, and hidden reasoning
are not supplied to the reviewer. A supported interpretation of a trace is not
proof that a perception caused the planner's choice; evidence can be incomplete.
