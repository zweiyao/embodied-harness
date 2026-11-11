# Remote networking separation and Qwen task-0 upload diagnostic

On 2026-11-11, ran one remote LIBERO `libero_10_task` task 0, seed 0,
with Qwen Flash (`qwen3.8-flash`), thinking disabled, the frozen iteration-11
R18+W2+F+V+A+I candidate and its unchanged W2 experience package. Budget:
600 seconds, 30 requests, 16384 output tokens per request. Original PNG images,
tools, prompts, source and task language were preserved. No JPEG conversion or
IP-family override was introduced. The continuous optimization loop stays paused.

Task instruction: “put both the cream cheese and the tomato sauce in the basket”.

## Measured result

| Measurement | Result |
| --- | --- |
| Official environment success | false |
| Termination | request budget exhausted, not 600-second timeout |
| Episode wall time | 261.2 s |
| Completed model responses | 30 / 30 |
| Native action calls | 11 |
| Task HTTP attempts | 31, including one recovered connection timeout |
| Image-bearing completed uploads | 29 |
| Image request JSON size | mean 3.158 MB; range 1.929–3.991 MB (decimal) |
| Upload interval | mean 4.014 s; median 3.258 s; range 1.268–12.826 s |
| Upload complete to response headers | mean 2.487 s; range 0.921–6.559 s |
| Application model request to model response | mean 7.481 s; range 3.175–17.489 s |

The client spent 116.402 seconds sending the 29 image request bodies, versus
224.427 seconds in all 30 application model-response spans. One connection
attempt timed out at approximately 5 seconds before any upload; the existing SDK
retried and completed that logical request. All logical requests completed.
The run remains a diagnostic only, excluded from formal success-rate comparisons
because it contains that transport incident. It is not evidence of a success-rate
improvement. The observed task endpoint is retained without reclassification.

The instrumented HTTPX2/HTTPCore2 path records real `send_request_body` boundaries
without changing transport selection, request content, retries, timeouts or
stream consumption. Body timing is a client write interval, not a server-side
receipt measurement. Waiting for response headers includes network, server
queueing and model processing, and cannot be called pure thinking time. Recorded
model settings confirm `enable_thinking=false` on all 30 requests. Image-bearing
requests are identified from recorded `image/png` content, not a size heuristic.
Some body-stream closures report `GeneratorExit` after the SDK has constructed a
complete model response; these are not independently classified as API failures.

This run did not reproduce the earlier sustained upload stall. Earlier diagnostics
also ran direct, so the faster timings cannot be attributed causally to removing
proxy code. Endpoint load, cache and time vary; no matched speed comparison was run.

## Network changes

- Added `deploy/remote-network.sh`, installed remotely as
  `/home/zwy/work/embodied_harness/remote-network.sh`. Explicit `direct`, `proxy`
  and `status` modes affect the invoking shell and user systemd manager.
  Proxy mode requires an existing remote loopback HTTP proxy. No proxy process
  is started, no existing service is restarted, and Mac networking is untouched.
- Removed 14 proxy-setting/loading lines from 9 of 11 examined remote general
  launchers, plus the corresponding network overrides in two local launcher
  copies. Removed hardcoded proxy exports from the repository UniVTAC launcher.
- Removed two network-only service overrides that otherwise superseded the
  selected manager environment; ran `daemon-reload` without restarting services
  for these removals. Existing processes retain their previous environment.
- The new task runner and launcher inherit networking. Its setup removes the
  historical batch's `unset ...PROXY` and explicit empty `ProxyHandler` overrides
  when preparing new runnable copies. The process observer checks networking
  read-only. Completed historical snapshots and backups remain unchanged and
  are explicitly disallowed as uncleaned templates in AGENTS.md.
- Kept original harness local-only MCP safeguards and Codex adapter behavior;
  neither is a model-provider proxy switch in these Qwen experiment scripts.

Remote backups are under `backups/network-separation-20261111/`. They may contain
private configuration and are not committed. Patches and hashes describe only
the scoped removals. The dedicated switcher selected direct mode before startup;
the live observer found no proxy variables in the diagnostic workbench or its
simulator process. No robot hardware was accessed.

## Validation and artifacts

- Real offline HTTPX2 fixture verifies byte-identical request body, preservation
  of an existing trace callback, cancellation propagation, separate upload/server
  wait timing, and exclusion of payload and authorization values from logs.
- Shell syntax checks pass; isolated fake-systemd checks cover direct/proxy/status
  and invalid endpoint rejection without changing real networking during tests.
- Runtime observer coverage complete, no guard violations. All 322 protected
  source/material/configuration files matched before publishing the history entry.
  The diagnostic service stopped cleanly and the runner exited successfully.
- Published one history root: 195 previous record IDs preserved, 196 total,
  instruction present. Only the idle LIBERO main web service was restarted for
  indexing. Existing configuration normalization changed `reasoning_effort` from
  null to `"none"`; the initial exact-equality assertion caught this, and the final
  verification records it explicitly. No other session configuration difference.
- Mac read-only HTTP checks confirmed the record and video (`206`, `video/mp4`).
  No browser visual inspection was performed.
- Harness source was unchanged; the full unit suite was not rerun for this
  operational cleanup and isolated tracing wrapper. Targeted checks are recorded
  separately. No new task trials were launched after the diagnostic.

[Record and video](http://10.162.250.228:8092/runs?id=e803259c39bda01a41bc)

Raw events, observations, videos and transport trace remain remotely under
`experiments/qwen-task0-upload-20261111/`; only sanitized timing summaries,
scoped changes and diagnostic source are committed. The script copies in
`scripts/` were formatted after the run; formatting and import cleanup preserve
behavior and the trace fixture was rerun. The runner setup depends on the frozen
iteration-11 archive and copies it into a fresh directory, stripping its network
overrides; it does not rerun or modify the archive.
