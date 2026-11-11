# Direct API address-family diagnostic

The four bounded requests do not establish a reliable IPv4 advantage. The initial IPv6/IPv4 totals were 20.65/14.45 seconds; the reversed IPv4/IPv6 totals were 25.28/24.85 seconds. All four returned HTTP 200 and OK, used verified requested peer families, and sent the same 1,801,183-byte JSON body containing the same three initial PNGs.

Body transmission occupied about 11.5–21.9 seconds; response headers arrived about 2.9–4.1 seconds after the client reported body-send completion. Client completion is not remote ACK. Both families therefore incurred material upload time in this diagnostic, while the order-reversed totals were nearly equal. Four sequential requests cannot separate all endpoint, cache, route and time variation.

This used raw httpx 0.28.1/httpcore 1.0.9, not the planner's reported httpx2 2.13.1. It does not validate planner integration. No global proxy, DNS, hosts or harness changes were made; no simulator episodes or actions ran. Both diagnostic units exited successfully, original workbench/config matched, and 6,017 protected hashes remained unchanged.

Separate diagnostic cost: 4 model requests, 8,588 input tokens including 6,144 cached, and 8 output tokens. The two iteration-05 timeout failures remain unchanged.
