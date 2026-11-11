# Hypotheses

H1: Proxy routing adds most latency. Test alternating identical direct/proxy calls on Mac and server.
H2: Provider queue/prefill/output dominates. Test connection vs first-content/complete timings, short vs representative long inputs.
H3: SDK retries or client setup adds latency. Compare standalone calls with installed client behavior and historical per-request events.
H4: Thinking is unexpectedly enabled. Inspect effective settings and returned reasoning usage; current source explicitly disables it.

At most 15 bounded diagnostic iterations; no robot/simulator action or harness modification.
