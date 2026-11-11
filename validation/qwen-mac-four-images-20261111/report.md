# Mac replay of the identical remote four-PNG request

User explicitly requested one local Mac test. One Qwen Flash request used the
same four unmodified PNG bytes, short question, base64 strings, model, output
budget (128), thinking=false and stream settings as the remote simple probe.
The JSON body is byte-identical: 3,619,985 bytes; SHA256 in metadata.json agrees
with the remote forced-IPv4 probe. Original PNG bytes total 2,714,531. No tools
or conversation history were added. The existing API credential was retrieved
through SSH into process memory and was neither printed nor written to disk.

Mac curl `--noproxy '*'`, without a forced address family:

- HTTP200, normal stop, complete response: 15.130670 seconds.
- First text/tool content: 14.385643 seconds (local wrapper timing).
- First response byte: 14.372315 seconds (curl timing).
- DNS/TCP/TLS completed by 0.058150 / 0.212369 / 0.548877 seconds.
- Input 4139 tokens (4104 image + 35 text), cache0, output40 tokens.
- Mac proxy settings matched before/after (`scutil --proxy`); no networking changes.

Previously the identical request on the remote host timed out at 120 seconds on
its default route, and returned in 16.988581 seconds when forced to IPv4. The Mac
result shows a 3.62MB PNG request can complete; it does not establish that PNG is
inherently unreliable or Mac egress is consistently faster. These are sequential
single probes at different times, with different curl versions and no paired
concurrent route control. No stable speedup factor or pure-upload latency is
claimed. The local clock starts after retrieving source material over SSH, so SSH
retrieval is not included in API latency. JPEG was not used in this test.

No new robot experiments, harness changes, image changes or proxy changes.
The research loop remains paused. Validation checked payload byte count/hash,
HTTP/exit status, cache counters and unchanged Mac proxy settings. No software
implementation changed, so no unit suite was rerun.
