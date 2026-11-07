# Findings

Historical Qwen returned-request mean was 19.8 seconds original / 51.3 seconds empty-memory. These include service/inference/transport, not pure network latency. Current endpoint is Aliyun Beijing, thinking disabled in source, workbench inherits proxy environment.

## Iterations 1–4

1. 12 short streaming probes, three per host/route: server direct 0.652–0.796 s, proxy 1.200–1.473 s; Mac 0.540–0.641 s. Thinking disabled, all 200. This disproves large fixed per-call latency but does not characterize large requests.
2. Rehydrated archived bytes through the installed provider with a mock HTTP transport. Identical 17-tool requests are 17.8 KB / 1.83 MB / 4.66 MB, containing 0 / 3 / 6 images. Model-only replay returns tool calls which are discarded. Server 1.83 MB proxy 47.76 s vs direct 7.07 s; 4.66 MB proxy hits 90 s, direct 14.29 s; Mac 4.66 MB direct 11.06 s. Cache hits and output token counts differ, so totals are not a pure controlled network effect.
3. Transport tracing confirms body transmission dominates several server waits: 4.66 MB legacy HTTPX cold sends in 9.53 s, headers follow 2.46 s later. HTTP/2 comparison unavailable because the optional h2 dependency is absent; no environment dependency changes made.
4. Installed HTTPX2 pool expiry experiment: 5-second expiry reconnects after a 7-second gap; 60-second expiry reuses the connection but the second body send takes 27.87 s and total 32.36 s. Connection reuse is confirmed, a speed gain is not. Do not deploy this alone. A gzip-encoded short request is rejected with 400 invalid_parameter_error; no gzip rollout.

A temporary loopback-only Mac relay with an SSH reverse tunnel is being compared against server direct, preserving request JSON and endpoint. No workbench settings changed.

## Iterations 5–6

5. Three alternating identical 4.66 MB requests: server direct median 23.31 s vs SSH-to-Mac median 6.04 s, all successful, identical input/cache counts. First-content medians 21.54 vs 3.46 s. Installed provider client succeeds through relay without retries (7.32 s total). This positively confirms a useful alternate egress path for this diagnostic load.
6. Candidate relay avoids stale pooled upstream connections by creating one per request. Three follow-up calls succeed in 5.01–9.19 s (median 8.43), with unchanged image/input counts. These are follow-up measurements, not an interleaved estimate. Candidate is not deployed in workbench. Temporary processes/tunnels closed; no environment actions.

Stop: transmission-stage bottleneck observed and a minimal reproducer/working egress alternative demonstrated. Production profile addition needs the concrete project approval documented in proposal.md. Long-term stability and task efficacy remain untested.
