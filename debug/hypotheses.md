# Isaac startup investigation — 2026-10-25

H1: NVIDIA 595 changes expose a compatibility bug in Isaac 4.5's RTX stack.
Test: obtain a native backtrace of the bare AppLauncher failure, then compare a
documented process-local compatibility setting or isolated newer RTX runtime.
If it crashes before NVIDIA/RTX initialization, this explanation is weakened.
Confidence: high, not confirmed on this host.
Specific candidate from NVIDIA repository issue 568: new drivers report
`VkPhysicalDeviceMaintenance3Properties.maxMemoryAllocationSize = UINT64_MAX`;
old RTX code incorrectly sizes scene resources. Compare unchanged AppLauncher
with/without a process-only Khronos Profiles property cap of 4 GiB minus 2 MiB.
No feature/extension masking or physics changes are part of this test.

H2: The independent environment loads conflicting graphics/C++ libraries.
Test: inspect actual shared-library resolution and compare a clean process-local
library environment. Unchanged native backtrace after correcting resolution
would rule out that specific library-path conflict.
Confidence: medium.

H3: Persisted Kit settings or caches cause the initialization crash.
Test: run the bare launcher with separate temporary data/cache paths and reset
settings, leaving the user's existing cache untouched. The same failure would
rule out persisted settings/cache as the sole cause.
Confidence: low.

Status after iteration 3: H1's allocation-property mechanism is confirmed by
the before/after query and bare AppLauncher test. H2/H3 are ruled out as necessary
causes (see eliminated.md). Continue implementation and real smoke verification;
the startup diagnosis alone does not close the user's task.

The driver, existing RPent virtual environment, simulator environment and running
services must remain unchanged during these tests. Do not reset a UniVTAC task
until startup/import probes pass. Scripted smoke is limited to the two reserved
development cells after that prerequisite.
