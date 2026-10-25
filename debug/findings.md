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
`Robots/Franka/GelSight_Mini/Gripper/uipc_gelpads_high_res_wrist.usd` still contains
a Git LFS pointer rather than the actual USD bytes.
The resulting exception is `Could not find prim with path
/World/envs/env_.*/Robot/gelpad_left.` The attempt is retained as setup_failure,
official_success=null, zero EEF commands, and counts 1/40. It is not retried or
reclassified. Official asset completion and a no-reset asset preflight are
required before the second reserved smoke. This is a separate setup issue,
not a recurrence of the RTX crash.

## Asset closure and authoritative preflight

The 25 GSmini LFS objects were hydrated with their committed size and SHA256
checks. A config-based no-reset probe then found two missing Grid textures and
an MDL module incorrectly treated as relative to the robot USD. The textures
were obtained from the official Isaac 2023.1.0 directory whose Grid USD exactly
matches the pinned local copy. `gltf/pbr.mdl` was already installed by Kit;
the probe now resolves it through the actual registered MDL search paths.
No robot, task, physics or USD definition was edited.

`artifacts/isaac-startup-20261025/asset-probe-complete/probe-result.json` reports
`probe_passed`, `headless_imports_passed` and `local_assets_passed` all true in
7.49 s, with 18 checked local files and no errors. Remote URL references are
listed as unchecked; this is not a promise of availability of every upstream
server. The probe never constructed/reset a task. It saves its structured
result before Kit closes, because Kit can exit zero even after Python failed.

The second fixed smoke cell uses a snapshot of 34 adapter/evaluation source
and launcher/provenance files under
`artifacts/isaac-startup-20261025/dev-02-runtime/`. The supervisor requires both
a completed ledger and a clean child exit; close-time failures cannot count as
a passed workflow. CPU verification passed 118 UniVTAC checks and six isolated
supervisor failure cases. The latter used fake child processes, not simulator
episodes. Raw failed preflights and the first smoke remain unchanged.

## Second smoke and follow-up calibration repair

`dev-02` (insert_hole, seed 1) finished in 155.99 s; the supervisor finished in
158.33 s with exit 0, no error and `workflow_passed=true`. The native expert's
direct `check_success()` returned true. The native `eval_success` cache remained
false because that expert path does not update it; both values are preserved.
The explicit hold command executed once over two physics steps, with position
error 1.19e-5 m and orientation error 1.98e-5 rad. There are 408 archived physics
steps and no partial files. The 864,986-byte video decodes fully: 388 frames,
1120×320 at 10 fps, with FFmpeg exit 0. Native pre-move sections are excluded
from video, so video frame count is not the physical step count.

This is a successful expert task and software shutdown, **not a complete
calibration acceptance**. During the run the EEF moved 7.74 cm while recorded
wrist extrinsics remained unchanged. Isaac Lab's CameraCfg defaults
`update_latest_camera_pose=False`; TiledCamera therefore reports its initial
pose. The adapter now enables that flag for its configured cameras before
constructing the task. Official task code, control and physics are unchanged.
The old dev-02 wrist extrinsics are invalid for world-coordinate projection and
must not be silently repaired or used as valid geometric maker evidence.

An independent, robot-free camera scene reproduced the old behavior and checked
the repair without reserving/resetting a UniVTAC episode. Both camera parents
moved 0.10 m: the default camera reported no movement, while the refreshed camera
reported 0.10000000149 m and matched the USD world pose and ROS orientation.
All eight checks passed; both images had 6,144 finite depth pixels. Reproduction
source: [camera_pose_check.py](camera_pose_check.py). The first camera-only check
passed its measurements but timed out while closing Kit. Its records are kept.
The diagnostic now unsubscribes the standalone SimulationContext stop callback
and releases render resources before closing. Repeated camera-only verification
passed all eight checks and exited 0:
`artifacts/isaac-startup-20261025/camera-pose-check-clean/camera-check.json`,
`camera-cleanup.json` and the adjacent `camera-pose-check-clean.exit`.
Kit exits its Python process inside `app.close()`, so a missing post-close Python
marker is not itself a failure; the saved exit status and absence of cleanup
errors are required as well. No full task was repeated after this observation-only
fix, and neither standalone camera scene used a pilot episode.

Real smoke sensors have two 270×480 RGB views; tactile RGB is 240×320 per finger,
with 64×2 marker coordinates and consistent current-minus-reference displacement.
Wrist depth was finite. Head depth has 84,036 positive-infinite pixels out of
129,600, the native no-return/clipping representation; consumers must mask
non-finite depth, not treat it as a measured distance.

Final regression: 119 remote UniVTAC tests passed, plus six supervisor checks.
The pilot used 2/40 attempts and 0/80 offline requests; no GPT/Max calls ran.
Final verification after the camera cleanup test confirmed that the original
RPent services retained their PIDs/start times, the workbench was ready, and GPU
use returned to 17,063 MiB on unchanged driver 595.80. The restored local web
forward also returned a healthy session response. Consolidated evidence is in
`artifacts/isaac-startup-20261025/verification.json`. Runtime records remain
remote; only source, tests and documentation are committed.
