# R source provenance

The new R checkout was copied from the verified frozen P working tree after all302 parent manifest entries matched. Relative to P, only `robots/libero/research/manual.py`, `robots/libero/robot_spec.py`, and `rpent/dashboard/workbench.py` changed; `robots/libero/research/orientation.py` is new. The resulting manifest has303 entries.

P's inherited differences from M/live remain documented in `../placement-preview/source-differences.json`; R is not described as the live tree plus one new tool. The older copied Git HEAD is retained in the handoff, while actual source hashes identify the evaluated content. Seventeen critical API/session/tool/controller/P files were additionally compared byte-for-byte with P. No transport or image change was made.

The selected candidate set is a separate experiment artifact: P19 minus the actual native names `rotate_wrist` and `rotate_pitch`, plus `rotate_axis`, yields18. The default catalog still includes the original rotation tools and excludes R. Its implementation does not depend on exposing `move_eef` to the policy.
