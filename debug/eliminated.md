# Eliminated explanations

Previous evidence (2026-10-24): a bare AppLauncher without RPent or UniVTAC task
construction also segfaults, so the task adapter and robot control logic are not
required to reproduce the renderer startup crash. Setting DISPLAY=:1 and an
NVIDIA-only Vulkan ICD removes display warnings but leaves the crash unchanged.
An isolated TLAS instance-limit override also failed; this is not a retained fix.

These results do not establish the exact native fault or a compatible driver.

2026-10-25: The same independent environment, shared libraries, settings and
caches start successfully once only the reported Vulkan allocation property is
capped. This eliminates H2 (a library-path conflict) and H3 (persisted settings
or cache corruption) as necessary explanations for this startup failure. No
replacement environment or cache deletion was used to obtain success.
