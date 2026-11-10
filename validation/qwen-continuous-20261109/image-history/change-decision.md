# I: recent image history (pre-implementation decision)

Scope: isolated LIBERO/API candidate derived from iteration10 A. Existing continuous
optimization authorization applies only within this protocol. Default false;
main workbench, original native behavior, W2 experience, F/V/A, 18 tools, model,
600s/30 requests/16384 output tokens, two environments and official scoring stay.

Evidence: iteration10/image-history-census.json. Final outgoing contexts contain
15/18 images (10.94/10.23MB raw). Completed request latency grows in these two
trajectories but varies with the same payload; no causal speed claim. Task4 first
held-feature point misses the current mug; stale-image influence is a hypothesis,
not a proven explanation. Neither trajectory completed its task.

Exact four-file production draft: implementation.patch.draft, with parent hashes
in base-hashes.json. Add server-owned api_recent_image_history=false, frozen into
the claimed task and forwarded through build_planner. The planner conditionally
inserts a supported SDK capability before request journaling. It retains binary
images in the newest two image-bearing ModelRequest groups (not two timesteps),
replaces older image items with the exact notice below, and preserves text,
tool returns/calls, timestamps and other metadata. Audio/non-image content stays.
Saved images and raw journal artifacts are never deleted. Explicit read_image
returns an old artifact in a new group. No resizing, encoding, model, proxy or
controller change. Core implementation contains no LIBERO policy.

Notice: [Earlier image omitted; use read_image to inspect it again.]

Risks: missing older useful visual evidence, extra rereads, prefix-cache loss,
and two groups may cover only overlays from one frame. This is an image-context
intervention, not a network repair; gains in latency or adoption alone do not
prove success improvement. The existing SDK sliding window remains unchanged.

Validation before policy launch: installed SDK FunctionModel multi-observation
requests verify two retained groups and byte identity, text/tool metadata and
non-image preservation, input immutability, explicit historical read_image,
default-off/no-images behavior; journaling must see the exact outgoing trimmed
request. Test server-owned boolean, API/LIBERO restriction, claimed-task freeze,
factory/CLI forwarding; run affected tests, full unit suite and required hooks
remotely in a new checkout, preserving the parent and original. Audit source and
language-material hashes. Only then stage fresh task0/4 seed0 cells (iteration11),
retain every valid failure, inspect real request images/latency/cache/use and
verify official outcomes and cleanup. Do not promote unless outcome supports it.
