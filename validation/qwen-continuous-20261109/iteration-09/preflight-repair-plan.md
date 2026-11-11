# Preflight01 repair, recorded before modification

No task was submitted. Both owned workbench units stopped after catalog equality
failed, before model connectivity checks. The launcher's RPENT_TOOL_CATALOG
includes shared LIBERO/UniVTAC/Flexiv declarations, while setup constructed its
expected list without that setting. Only source_robot/supported_environments
on finish/list_dir/read_text_file/write_text_file differ in both lanes; tool
versions, descriptions, schemas and selection remain identical.

Retain original preflight report, journal, READY/launch metadata, setup.py and
both expected catalogs under preflight-01. Reconstruct expected catalogs using
the same declared catalog configuration as the lane launchers, and teach setup
that exact setting. Keep strict whole-catalog equality, with no added exclusions.
Update only the related protected hashes and READY generation after checking
no task artifacts exist and every other protected file remains unchanged.
Re-run scoped lint/compile and compare the changed catalog field set exactly.
Then relaunch preflight for the same unstarted cells; this is preparation repair,
not a replacement trial or a benchmark result. Source, material, controllers,
budgets, Mac and original services remain unchanged.
