# Candidate T publication

After the isolated validation passed, the parent agent reviewed and authorized publication into a new independent library. This extends the implementation-only scope recorded in `tool-change-plan.md`; the current C/E experiment continues using its frozen old library and sources.

- Library: `/home/zwy/work/embodied_harness/tool-library/qwen-continuous-20261109`
- Version: `eb961cc0f520a6b5f6814fad350af7a285a2725c9b50c442b8267745ad1b9195`
- Tool JSON SHA256: `5b49561b7595b1502ef4da1fab3599d2b09942ffb1c55e5fb4c8f39a730eac22`
- Prior version: `553831b20799170badced4a5ea5dde8ef75d8e38a50527ca7debe01cb7fdf5bf`

The old `qwen-evidence-v3` library was copied before publication. The existing publisher removes previous same-name entries from its target directory, so its copied predecessor JSON and metadata were restored byte-for-byte from the unchanged old library. Final verification confirms the new library contains the old four files plus only the new T JSON and metadata. All old-library hashes remain unchanged. No current service configuration, selected tool set, or live runtime source was changed.

The archived Docker replay used recorded task 4 step 1, explicit `step=1`, and same-frame traceable pixels. Parameters and bounded numeric output are saved in `tool-replay-params.json` and `tool-replay-result.json`. The target was independently recomputed from archived world patches and EEF position; its XY composition and unchanged Z matched. This establishes calculation/execution only: pixel identities, confirmed holding, obstacle clearance, adoption, and task benefit remain unverified. The archived prefix ends at step 1; stale-step rejection is instead covered by unit fixtures that include a later frame.

The existing workbench selection function resolves the explicit `generated:<new version>` ID to the new source even with both versions present. Selecting both same-name versions is rejected by the existing uniqueness check. A later E+T condition must replace only the old patch ID with the new ID, preserving all other selected tools. T has not been selected for the current C/E experiment.

Validation: focused file 27 passed; research directory 76 passed / 4 skipped; full unit suite 2045 passed / 15 skipped, all in the remote isolated checkout. Scoped pre-commit passed for the T files and separately for `audit_task_definitions.py`. Full repository pre-commit was not rerun; unrelated historical findings remain. No model requests or simulator actions were made for these checks. See `tool-validation.json` and `tool-publication.json` for hashes and scope.

Publication command, run from the isolated checkout:

```sh
/home/zwy/work/harnessvla/.venv/bin/python -m robots.libero.research.manual_library \
  --library /home/zwy/work/embodied_harness/tool-library/qwen-continuous-20261109 \
  --candidate examples/manual-workbench/candidate.json \
  --metadata /home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/tool-candidate-metadata.json \
  --replay-run /home/zwy/work/embodied_harness/experiments/qwen-flash-eef-screen3-20261109/b/runs/session/tasks/0001_libero_10_task_t4_s0 \
  --step 1 \
  --params '{"points":[[0.5669599217986315,0.7135874877810362],[0.6647116324535679,0.04887585532746823]],"camera":"agentview","step":1,"radius":1,"alignment_pair":[0,1]}'
```

`tool-candidate-metadata.json` preserves the input metadata before replay; its pending validation text is historical. The published metadata and `tool-publication.json` record the completed replay.
