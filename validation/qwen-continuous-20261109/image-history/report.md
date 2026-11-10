# I image-history candidate: software validation

Four production files implement the recorded default-off draft. Both binary-image
locations used by the installed SDK are covered: UserPromptPart and ToolReturnPart.
Only list/tuple image content is transformed; text, audio, metadata and saved
artifacts remain. The new capability runs before request journaling.

Remote isolated checkout: image-history-test-checkout, copied from A after checking
303 parent source hashes. Main service and parent files were not deployed over.
Actual SDK multi-turn tests cover enabled/disabled/no-images, preserved bytes,
explicit old-image reread, tool/text history, outgoing journal equality, copied
input metadata/audio, boolean checks, factory and claimed-config persistence.
2188 passed /15 skipped (74.20s);128 focused tests (5.60s) and six-file scoped hooks passed.
Full pre-commit still reports18 historical validation-script diagnostics; first
new-test import/dict-style lint failures are retained and were corrected before
pytest. Full CI Python matrix and policy performance are not verified.

Additional provider HTTP-body tests confirm exact retained image bytes and
preserved tool-call IDs, thinking=false and tool_choice=required. Enabled and
disabled variants preserve30-request exhaustion, physical timeout draining and
Dashboard replacement cancellation.303 parent source hashes remain unchanged;
the candidate differs in exactly four production files.22 native declarations,
native/calibrated/A prompts and seven W2 materials are identical to the parent.
source-handoff.json freezes the candidate source for fresh runner preflight.
No new external policy requests or simulator actions occurred. Task success,
latency and cache benefits remain untested; the full CI Python matrix was not run.

Research steering: the user requested online methods of capability transfer.
The image-window candidate remains isolated while that review informs the next
hypothesis. It is not promoted, and no success or latency benefit is claimed.
