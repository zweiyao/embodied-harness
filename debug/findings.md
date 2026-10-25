# Isaac startup investigation — 2026-10-25

## Symptom and constraints

Isaac Sim 4.5 / Lab 2.1.1, isolated Python 3.10, Ubuntu 24.04.4,
NVIDIA 595.80, RTX 4090 48 GB. Bare AppLauncher segfaults while creating the
Hydra viewport, before constructing or resetting any UniVTAC task. Prior logs
include `Buffer size instance limit -256` and
`TLAS limit : valid true, within: false`. No known working startup on this host.

At investigation start the existing RPent workbench and board services are
active, and GPU use is 17,063 / 49,140 MiB. Preserve that installation. Raw logs
stay outside Git under the remote workspace's artifacts/external directories.

## Prior evidence

- `external/headless-probe.log`: original startup failure.
- `external/headless-probe-display.log`: display/ICD-only change, still failed.
- `external/headless-probe-cap.log`: bare AppLauncher + capacity override, failed.
- NVIDIA issue 537 reports a similar RTX/Hydra failure on 595 and recommends a
  validated driver: https://github.com/isaac-sim/IsaacSim/issues/537 . This is
  supporting evidence, not confirmation of the root cause on this machine.

No smoke cells or model experiments have started in this investigation.

## Iteration 1 — native reproduction

The clean SSH process has no LD_PRELOAD/LD_LIBRARY_PATH overrides. NVIDIA ICD
is `/etc/vulkan/icd.d/nvidia_icd.json`; display :1 exists. A bare AppLauncher
is run under batch gdb with only process-local DISPLAY, ICD and EULA variables.
Raw command/script/backtrace are retained under
`artifacts/isaac-startup-20261025/` on the remote workspace.

A newly found community reproduction documents a process-local allocation-limit
workaround: https://github.com/isaac-sim/IsaacSim/issues/568 . It has not yet been
verified for this host's Isaac 4.5 environment; no runtime patch is applied yet.

Result: gdb caught SIGSEGV in `librtx.scenedb.plugin.so`, with four top frames in
that library, followed by `libcarb.scenerenderer-rtx.plugin.so` and Hydra. NVIDIA
graphics libraries consistently resolve to 595.80; libvulkan is the bundled
Isaac library and libstdc++ is from the independent prefix. This narrows the
failure to native RTX initialization rather than Python task code. Raw gdb exits
0 after reporting the stopped process; that is not a successful application exit.

The current driver was installed through NVIDIA's installer/DKMS, not apt, and
is shared with the existing RPent GPU services and desktop. No driver operation
was attempted. A standalone build of Khronos Profiles is being prepared outside
both environments for the allocation-property comparison.

## Iteration 2 — check that the compatibility layer is actually active

The direct Vulkan query confirms the suspect property on this host:
`maxMemoryAllocationSize = 18446744073709551615 (UINT64_MAX)`.
The first compatibility query returned the same value: the layer was not loaded
through `VK_ADD_IMPLICIT_LAYER_PATH` alone. This is a failed activation test, not
evidence that the property cap cannot fix the renderer. Use a process-local XDG
implicit-layer directory supported by the older loader and repeat the query
before claiming compatibility is enabled. No global layer registration occurred.

## Iteration 3 — confirmed process-local fix

Adding the independent directory to XDG_DATA_DIRS allowed the old Vulkan loader
to find the opt-in Profiles layer. The same read-only query now returns
`4292870144 (0x00000000ffe00000)`. Device, driver and API version are unchanged.
The same bare AppLauncher reached `BARE_APP_READY` and exited 0 using this
property cap; the unchanged baseline failed with SIGSEGV/139. No driver, Isaac,
Lab, CUDA, task code or settings/cache reset was needed. This positively confirms
the allocation-property workaround for the startup crash on this host.

Evidence: `property-baseline.txt`, external `isaac-rtx-compat/query-compat.log`,
`bare-gdb.log`, `bare-compat.log` (inactive-layer failure), and
`bare-compat-xdg.log` (successful startup). A full UniVTAC import probe follows
before reserving any task. Passing startup does not establish task success.

## Full import probe and first smoke

The full `robots.univtac.probe` printed `headless_imports_passed: true`, CUDA
available, and `episode_started: false` in 7.90 s, then exited 0. Its package
metadata reports Isaac 4.5.0.0, torch 2.5.1+cu124; source revisions remain pinned.

`tactile-pilot-20261025/dev-01` was then reserved once. Renderer startup succeeded,
but task construction failed because the referenced official TacEx robot USD
`Robots/Franka/GelSight_Mini/Gripper/uipc_gelpads_high_res_wrist.usd` is absent.
The resulting exception is `Could not find prim with path
/World/envs/env_.*/Robot/gelpad_left.` The attempt is retained as setup_failure,
official_success=null, zero EEF commands, and counts 1/40. It is not retried or
reclassified. Official asset completion and a no-reset asset preflight are
required before the second reserved smoke. This is a separate setup issue,
not a recurrence of the RTX crash.
