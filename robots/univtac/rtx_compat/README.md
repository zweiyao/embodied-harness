# Private Vulkan compatibility layer

This optional setup targets the old Isaac RTX startup failure where the log
reports `Buffer size instance limit -256` and the crash enters
`librtx.scenedb.plugin.so`. Newer drivers can report `UINT64_MAX` for
`VkPhysicalDeviceMaintenance3Properties.maxMemoryAllocationSize`; this partial
Khronos profile reports **4 GiB minus 2 MiB (4292870144 bytes)** instead. That is
the reported limit for **one allocation**, not a total VRAM cap.

The technique comes from the [Isaac Sim issue 568 discussion](https://github.com/isaac-sim/IsaacSim/issues/568)
and an [independent Isaac 5.1 reproduction](https://mirtith.github.io/blog/isaac-sim-5.1-new-nvidia-driver-rtx-crash/).
On the existing RTX 4090 / NVIDIA 595.80 host, property queries verified the
override and its process isolation. Bare Isaac 4.5 AppLauncher changed from
SIGSEGV/exit 139 to `BARE_APP_READY` and exit 0. Full task execution is a
separate verification. This is not a general compatibility guarantee for
other drivers, renderer versions or GPUs.

The upstream [Khronos layer](https://github.com/KhronosGroup/Vulkan-Profiles/tree/v1.4.341)
is pinned to `fbbca14527706745b1c899ca10fc6ad4453f2280` (v1.4.341), Apache-2.0
for its C++ layer. Original source notices and dependency licenses remain in
the external checkout. No upstream layer source or binary is stored in Git.
`query.c` is a small local property reader; it creates no device or scene.

## Install explicitly on the remote host

Prerequisites: existing Git, a C/C++ compiler supporting C++17, CMake >=3.22.1,
Python with `jsonschema`, and the Vulkan loader. The verified build used GCC
13.3, CMake 3.28.3 and system Python 3.12.3. The script installs no system
packages and does not alter the existing simulator environment. Build logs,
downloaded sources and outputs must stay outside the repository.

```sh
cd /home/zwy/work/harnessvla
python3 robots/univtac/rtx_compat/install.py \
  --prefix /home/zwy/work/embodied_harness/external/isaac-rtx-compat \
  --python /home/zwy/work/embodied_harness/external/univtac-env/bin/python \
  > /home/zwy/work/embodied_harness/external/isaac-rtx-compat-build.log 2>&1
```

The explicit install downloads pinned upstream sources, builds the layer and
query, then writes `provenance.json` with dependency commits, commands and
SHA256 hashes. It refuses a changed or unexpected source checkout. It does
not execute Vulkan, start Isaac or reset a task. There is no download or
build during normal simulator startup.

## Compare properties, then launch the existing probe

```sh
cd /home/zwy/work/embodied_harness/external/isaac-rtx-compat
VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json ./query
( . ./enable.env
  VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json ./query )
```

On the affected host these return `18446744073709551615` and `4292870144`
respectively. `VK_LOADER_DEBUG=layer` also shows whether the layer was loaded.
A property query alone does not prove that Isaac or a task works.

Pass the generated absolute `univtac-python` path as RPent's
`--univtac-python`. This wrapper adds its private `xdg-data` directory to
the child process's `XDG_DATA_DIRS`, preserving the previous value or the
standard `/usr/local/share:/usr/share` default. It enables only the property
profile, then executes the existing simulation Python with unchanged arguments.
Missing build/configuration files produce an explicit startup error. Set
`RPENT_VULKAN_COMPAT_DISABLE=1` for an explicit unmodified comparison through
the same wrapper; otherwise leave this variable unset.
No global/user Vulkan registration, shell startup file, driver, policy,
controller or benchmark predicate changes. Do not source `enable.env` in a
login shell or unrelated long-lived service.

First run the [existing no-task probe](../INSTALL.md) using that wrapper.
Only after infrastructure verification should the trusted runner reserve a
pilot cell and launch a smoke episode. Switching back to the original
`univtac-env/bin/python` bypasses the layer; no driver restart is required.
