# Independent Linux deployment

Use a new Python 3.10 environment. Do not run the upstream `scripts/install.sh`
unattended: it changes shell setup, uses sudo, launches training and collects
episodes. The following records the reviewed components used by this adapter;
it does not authorize any task reset or consume pilot episodes.

Current deployment directories are under
`/home/zwy/work/embodied_harness/external/`, with Python at
`univtac-env/bin/python`. Source checkouts and large assets stay outside Git.
RPent remains under `/home/zwy/work/harnessvla` in its existing environment.

1. Create a new conda prefix with `python=3.10`, `pip`, `git-lfs`,
   `cmake=3.26`, `ninja`, `gcc=11.4`, `gxx=11.4`, `cuda-toolkit=12.4`,
   and `pkgconfig` from conda-forge. Install ffmpeg 6.1 in the prefix or a
   separate private tools prefix with an executable symlink in the Python
   prefix's `bin/`. No system CUDA or user environment needs replacing.
2. Clone UniVTAC with Git LFS smudging disabled and check out
   `0dafa10262e22f486f160a55d6f11aeab12d8e7b`. The needed task assets are in
   this checkout; do not download demonstration datasets or policy weights
   for the model-driven pilot.
3. In the new prefix install PyTorch `2.5.1` and torchvision `0.20.1` from
   `https://download.pytorch.org/whl/cu124`. Install
   `isaacsim[all,extscache]==4.5.0` using NVIDIA's package index. Pin
   `numpy==1.26.4`, `setuptools<82`, and `warp-lang==1.0.0` during subsequent
   installation. Build helpers include `wheel`, `toml`, `pybind11`, `mypy`,
   `pytest`, and `flatdict==4.0.1` (install flatdict without build isolation).
4. Check out Isaac Lab v2.1.1 at
   `90b79bb2d44feb8d833f260f2bf37da3487180ba` in
   `UniVTAC/third_party/IsaacLab`. Editable-install its `source/isaaclab`
   and `source/isaaclab_assets`, retaining the torch/numpy/warp pins above.
5. Check out cuRobo `0a50de1ba72db304195d59d9d0b1ed269696047f` in
   `UniVTAC/third_party/curobo`. Editable-install without build isolation,
   with `CUDA_HOME` pointing at the new prefix, `TORCH_CUDA_ARCH_LIST=8.9`
   for this RTX 4090, and bounded `MAX_JOBS=4`.
6. Install compatible `torch-scatter==2.1.2` from the wheel links at
   `https://data.pyg.org/whl/torch-2.5.1+cu124.html`, using
   `--only-binary torch-scatter`. Its actual wheel is pt25/cu124. The
   bundled TacEx setup currently names a pt28/cu128 wheel, so install
   `debugpy`, `nvidia-ml-py`, `pre-commit`, `h5py`, `transforms3d`, `decorator`,
   `tetgen`, and `wildmeshing` explicitly with `numpy==1.26.4`, then
   editable-install bundled `source/tacex` and `source/tacex_assets`
   with `--no-deps --no-build-isolation`. Do not upgrade torch to satisfy
   that stale dependency URL.
7. Build bundled `source/tacex_uipc/libuipc` using the same CUDA 12.4/GCC
   11.4 prefix. The vcpkg checkout is pinned to
   `0c2a9ace1964b818b15f7ae50ba1c42404918a7b`; fetch its history because old
   port trees are required by the unchanged libuipc manifest baseline.
   Run `bootstrap-vcpkg.sh -disableMetrics` and set process-local
   `CMAKE_TOOLCHAIN_FILE` to its `scripts/buildsystems/vcpkg.cmake`.

   The baseline selects tinygltf 2.9.3, whose upstream regenerated tarball
   no longer matches the historical SHA512. Use the **official** tinygltf
   3.0.0#1 port from that pinned vcpkg checkout as an external overlay,
   retaining its SHA512 verification. This follows the upstream
   [archive hash fix](https://github.com/microsoft/vcpkg/pull/53226).
   Record this dependency difference; do not silently disable hash checks
   or alter UniVTAC task/physics/success code. Set `VCPKG_OVERLAY_PORTS`
   to the private overlay directory for both CMake and package installation.

   Configure CMake with `CMAKE_BUILD_TYPE=Release`,
   `CMAKE_CUDA_ARCHITECTURES=89`, `UIPC_BUILD_PYBIND=ON`,
   `UIPC_BUILD_GUI=OFF`, `UIPC_DEV_MODE=ON`, and
   `UIPC_BUILD_EXAMPLES/TESTS/BENCHMARKS=OFF`; these disable build targets,
   not simulation behavior. Then editable-install bundled `tacex_uipc`
   with `--no-deps --no-build-isolation`, preserving the configured build
   cache. Keep full build logs outside the Git repository.

Any proxy variables are scoped to the installation process and use the
remote host's existing proxy. Do not change the user's global proxy or add
a laptop reverse tunnel. Local RPC and simulation traffic stay direct.

Verification must use the remote environment. On the current 595.80 host, use
the private Python wrapper described in [rtx_compat/README.md](rtx_compat/README.md).
It enables the allocation-limit compatibility layer only in the simulator process.
Set `OMNI_KIT_ACCEPT_EULA=YES`
in the simulator subprocess environment, set `PYTHONPATH` to the RPent
checkout, and run `python -m robots.univtac.probe --root <UniVTAC> --output-dir
<private-log-dir>`. This imports the headless app and task classes without
constructing/resetting a task. Only after this succeeds should the trusted
runner reserve a pilot cell and start a scripted smoke or model episode.
The install commands alone do not establish that simulation works.

## Initial deployment state (2026-10-24)

The independent Python 3.10 prefix, Isaac Sim 4.5, Lab 2.1.1, cuRobo,
bundled TacEx and its UIPC native bindings were installed successfully. The
full resolved environment is retained outside Git in
`external/univtac-environment.lock.txt`. The adapter's 13 CPU tests passed
in both RPent's remote environment and the independent Python 3.10 prefix.
The latter also served a real loopback metadata request without resetting a
task. No simulator episode has been started.

**The initial headless startup failed.** On this host's NVIDIA 595.80 driver,
the renderer segfaults while initializing the Hydra viewport, before any
UniVTAC task is constructed. A process-local `DISPLAY=:1` and NVIDIA-only
Vulkan ICD removed the initial GL/display warnings but did not fix the
crash. A bare AppLauncher without the adapter/task code also crashes.
The Kit log reports `Buffer size instance limit -256` and
`TLAS limit : valid true, within: false` immediately before it stops.
An isolated renderer-capacity override did not help and was not retained
in the adapter.

Logs remain in `external/headless-probe.log`,
`external/headless-probe-display.log`, and `external/headless-probe-cap.log`.
This signature matches [NVIDIA's reported 595-branch RTX/Hydra problem](https://github.com/isaac-sim/IsaacSim/issues/537)
and a [4.5/5.0/5.1 renderer crash report](https://forums.developer.nvidia.com/t/isaac-sim-error-on-rtx-5060-gb-laptop-gpu/371956).
That is evidence for a driver/runtime incompatibility, not proof that a
particular replacement driver will work on this host. The dependency installation
did not change the driver, global proxy or existing simulator environment.

## Process-only startup repair (2026-10-25)

The real Vulkan property query returned `UINT64_MAX` for
`VkPhysicalDeviceMaintenance3Properties.maxMemoryAllocationSize`. Gdb located
the crash in `librtx.scenedb.plugin.so`. A private Khronos Profiles layer, built
from pinned upstream sources, changes only that reported single-allocation limit
to 4292870144 bytes. It does not restrict total VRAM to 4 GiB.

With the existing driver and unchanged Isaac/Lab environment, bare AppLauncher
now reaches ready and exits 0. The full UniVTAC task import probe also passed in
7.90 seconds, with CUDA available and no task reset. Configuration, source hashes,
the compiled library and runtime wrapper stay in
`external/isaac-rtx-compat/`; no global/user Vulkan layer is registered. See
[rtx_compat/README.md](rtx_compat/README.md) for reproduction and opt-out.

The first reserved smoke subsequently exposed a separate asset problem: the
GelSight Mini robot USD was still a Git LFS pointer. That attempt is retained as
`setup_failure`, not a task failure or a successful smoke. Real asset validation
is required before the second attempt; import success alone does not cover it.

After a trusted runner reserves a script cell, use the same independent
Python to run `python -m robots.univtac.smoke --root <UniVTAC> --output-dir
<reserved-output-dir>`. This requires `pilot-attempt.json`, records the
initial fingerprint before motion, verifies one unchanged EEF target,
then runs the native expert. Expert outcomes are environment diagnostics,
not model results or maker evidence. The directory cannot be reused for a
second reset, including after an interrupted run.
