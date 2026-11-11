# P source provenance

The P checkout is `/home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/placement-preview-test-checkout`, copied from the verified frozen M checkout. It adds `robots/libero/research/placement.py` and changes only `robots/libero/research/manual.py` and `rpent/dashboard/workbench.py` in the production source manifest. The new handlers register only when selected, and both remain excluded from defaults.

The 14 critical API/session/tool/environment files listed in `active-path-check.json` remain byte-identical to M. All 19 prior native declarations, their versions and four prior default/selected prompt snapshots match M exactly. The M version remains unchanged. Both P native IDs hash the complete placement module, so helper mathematics and rendering are included in the frozen version; their IDs and schema names are distinct.

This is not a claim that the entire checkout equals live plus P. It inherits M's previously documented inactive compatibility/dependency/format/documentation differences. See [M source differences](../motion-contract/source-differences.md). No dependency installation, original live edit, core planner change, old primitive change, or global controller change occurred. Runtime source identity is given by the 302 file hashes in `source-handoff.json`, not the checkout's older Git HEAD.
