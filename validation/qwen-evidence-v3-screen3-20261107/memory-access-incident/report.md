# Excluded memory export attempts

The first v3 export placed the approved notes below `memory/libero/`, but the memory tool treats `memory/` as the corpus root and rejects that extra directory. File existence and frozen prompt checks missed the actual tool access boundary. A read request was incorrectly described as a successful read; no approved note body was successfully returned in these attempts.

All three initial cells (tasks 0, 4, 8; seed 0) are excluded as implementation incidents. Tasks 0 and 4 had reached their 300-second limit; task 8 was aborted after the defect was identified. Their original events and outcomes remain on the remote host. Archived summary/status files describe the initial controller state, not valid evaluation results. `incidents.json` records the exclusion reason without observations or video.

The corrected independent export puts the identical three notes directly under the memory root and changes only their index paths. It preserves the permission implementation, original harness, original corpora, and system/user/guide contents. Preflight now freezes the material and actually reads every note with CommonTools; writes remain denied. A regression test covers allowed root notes, denied nested paths, and read-only behavior.

The three affected cells are retried once on two environments, all at the user's latest 600-second budget with 30 model requests. This is a development screen, not a comparison isolating budget or memory effects. Earlier v2 notes used the same nested export; no successful reads of those new note bodies were recorded, so those runs do not establish an accessible-new-memory condition.
