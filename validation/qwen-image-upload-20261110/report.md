# Image-upload solution screening

The immediate bottleneck is measured call waiting: iteration11 spent 95.73% /
88.73% of recorded elapsed time in completed model-request spans. This constrains
opportunities for action within a fixed budget, but does not prove that all task
failures would disappear with faster transport. Existing valid failures remain
recorded; no benchmark results were reclassified or experiments launched.

Earlier same-payload IPv4/IPv6 diagnostics did not show a stable address-family
advantage (see ../qwen-continuous-20261109/api-transport-diagnostic-20261110/).
The new tests therefore treat IPv4 as a candidate transport setting, not a proven
universal repair. All requests here used the existing remote Qwen Flash endpoint,
no proxy, no reasoning, no tools/history, max_tokens=128 and the same short question.

| Payload and connection | Request bytes | Total seconds | Notes |
| --- | ---: | --- | --- |
| Four original PNGs, default route (earlier probe) | 3,619,985 | 120 timeout | No response; not successful latency |
| Same four PNGs, forced IPv4 | 3,619,985 | 16.989 | HTTP200, no input cache |
| Same four images as JPEG85, default route | 462,869 | 29.390 / 6.802 / 3.485 | Cache 0 / 4096 / 4096; IPv6 / IPv6 / IPv4 |
| New frame sets 1/2/3, JPEG85, forced IPv4 | 428,529 / 413,569 / 462,581 | 4.544 / 3.948 / 4.106 | All HTTP200, all cache0, distinct payload hashes |

The final three independent image sets average 4.199 seconds, with first-content
latencies 4.297 / 3.753 / 3.297 seconds. All retained four 1024x1024 images and
reported 4139 input tokens (4104 image + 35 text). The same-frame initial JPEG
request was 87.21% smaller in bytes. All seven requests returned normal stop
reasons. Outputs were discarded and never dispatched to robot tools.

These observations support trying the combined JPEG/IPv4 option. They do not
isolate the contribution of each change: routing/endpoints, caching and time
varied, and the final fresh frames lack matched PNG controls. HTTP success does
not establish visual or coordinate accuracy. JPEG is lossy even at unchanged
resolution. The API supports JPEG and PNG input:
https://help.aliyun.com/zh/model-studio/vision/

Proposed deployment scope, not implemented: an opt-in transformation of RGB image
attachments immediately before the Qwen API call, preserving width/height and
view order, plus an owned per-client IPv4 transport retaining endpoint hostname
and TLS verification. Keep original PNG/depth/calibration artifacts and the
original harness path. Validate the actual SDK path, cancellation/lifecycle,
image/frame bindings, semantic target/point selection and a few matched full
requests before any task rerun. A concrete code diff still requires review before
deployment; the older IPv4 draft is not assumed compatible with current source.

No global DNS/IPv6/proxy settings, Mac network settings, model profile, prompt,
experience or harness code changed. No image files were edited; JPEG bytes existed
only in process memory and API requests. The research loop remains paused.
Validation checked all seven outcomes, image dimensions, fresh input identities,
cache counts and peer families. No unit suite was needed for evidence-only changes.
