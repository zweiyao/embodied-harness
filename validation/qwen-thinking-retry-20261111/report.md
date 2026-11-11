# Qwen Flash thinking and idle retry: task 0

The corrected single trial completed in 1068 seconds with 30 model responses,
43 tool calls and 12 action calls. Official success was false. It exhausted the
30-request budget; there was no episode time limit and no transport failure.
All 30 requests enabled thinking and all 30 responses returned thinking content.
Accepted-response usage included 42,686 reasoning tokens.

Task: `libero_10_task`, task 0, seed 0 — put both the cream cheese and the tomato
sauce in the basket. Existing tools, memory, PNG observations and output-token
budget were retained. The candidate changed thinking, tool-choice compatibility,
retry handling and the episode time policy together; this is a diagnostic trial,
not a controlled estimate of thinking's effect or success-rate improvement.

## Request timing and retry behavior

- Complete model-response time: mean 34.303 seconds; maximum 76.214 seconds.
- Image-bearing request upload: 26 requests, mean 10.231 seconds, maximum 28.054
  seconds. Mean serialized request size was 3,556,917 bytes. These are client
  transport upload intervals, not a separate measurement of provider ingestion.
- Upload completion to response headers: mean 3.122 seconds for image requests.
- 30 actual HTTP attempts, zero retries and zero transport failures. Requests 21
  and 30 exceeded 60 seconds but continued producing meaningful deltas and were
  accepted normally. Actual recovery from a stalled request was not exercised;
  those paths were verified with the installed SDK and offline fault injection.

The default-off candidate waits up to 60 seconds without meaningful reasoning,
answer or tool-function progress and retries once after two seconds. Complete
responses are buffered before tool scheduling to prevent executing abandoned
partial calls. HTTP parameter/authentication errors are not retried. Original
harness defaults and network settings were preserved.

## Excluded setup incident

The initial attempt returned HTTP 400 because Qwen thinking rejected
`tool_choice=required`. It executed zero actions, was preserved and excluded from
experimental task results. The corrected isolated checkout uses `auto` for
thinking while retaining the local finish-tool validator, then reran task 0.
Plain text alone cannot finish a task. No discarded incident was relabeled as a
model task failure.

## Verification and publication

Remote final unit suite: 2204 passed / 15 skipped; focused tests: 144 passed.
Scoped pre-commit passed. Full pre-commit reported pre-existing diagnostics in
historical validation scripts; unrelated hook edits were restored. This is not a
claim that repository-wide pre-commit passed.

Runtime observation coverage was complete with no guard violations. All 323
protected files were unchanged before publishing history. The owned lane stopped
cleanly. Main LIBERO history indexing was then extended to include both records;
all 196 existing record IDs and the session configuration were preserved (198
records total). Video access from the Mac returned HTTP 206 for a range request.
No Mac or remote networking changes were made. Continuous optimization remains
paused; only this corrected single trial was run after the excluded incident.

[Corrected experiment and video](http://10.162.250.228:8092/runs?id=044e1b51a5af76e717fa)

[Excluded incident](http://10.162.250.228:8092/runs?id=3f5daae39d82b1b872e1)

Evidence: `software-summary.json`, `verification-v2.json`, `upload-summary.json`,
`final-verification.json`, `initial-parity.json`, `history-checks.json`,
`mac-http-check.json` and `progress-update.json`. Raw observations, videos,
credentials and model weights remain outside Git.
