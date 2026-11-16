# RoboDojo research workbench

Use the shared RPent setup, console, tool catalog and run history with an
independent RoboDojo environment. No physical robot service is required.

1. Prepare the simulator, RLinf policy, normalization statistics, tokenizer and
   SAM3 as described in the paired RoboDojo simulator guide. Keep assets, private
   configuration and run data outside the checkout. The validated runtime is a
   prepared Python 3.11 stack; it is not a clean dependency-metadata result.
2. In a private runtime environment file, set `RPENT_REPO_ROOT`,
   `ROBODOJO_ASSETS_ROOT`, `PI05_CHECKPOINT_PATH`, `PI05_NORM_STATS_PATH`,
   `OPENPI_DATA_HOME`, `SAM3_CHECKPOINT_PATH`, `RPENT_RUNS_ROOT` and
   `RPENT_MEMORY_DIR`. Preserve the hardware-specific runtime settings already
   validated on that host. This launcher expects `.venv/bin/python` in the checkout.
3. Create a private Workbench JSON using the existing `robot`, `runs_root`,
   `library_root`, `models` and `setup.profiles` contract. Set `robot` to `robodojo`.
   Model profiles reference private `key_file` or `codex_home` paths; credentials
   do not belong in the configuration committed to Git.
4. Add a RoboDojo setup profile with its ports, label and note. Generate
   `task_fields` with `robots.robodojo.catalog.task_fields(source_root,
   assets_root, env_cfg_type)` from the actual installed source and assets.
   `robodojo_runtime.source_root()` supplies the packaged source root. Task names
   are native IDs and layout IDs follow SeedManager enumeration. Runtime language
   is resolved only after scene initialization.
5. Select networking externally on the remote host using `remote-network.sh`.
   Then start:

   ```bash
   bash deploy/start-robodojo-workbench.sh /private/runtime.env /private/workbench.json
   ```

The launcher binds `127.0.0.1:8094` unless `RPENT_DASHBOARD_PORT` is set. It starts
shared VLA/SAM3 services, with a fresh owned ENV only after a task command. Defaults
are 30 model requests, 4096 response tokens, a 600-second planner budget and 700
native actions subject to the official task's lower cap. Use a separate empty
local memory corpus for baseline checks; the launcher does not add experiences.

For a user systemd service, use `KillSignal=SIGINT`, `KillMode=mixed` and a stop
budget long enough for owned servers to drain. Validate stop and restart while no
task is running. An external LAN relay must bind a specific host address, expose
only the dashboard port and retain the operator source-IP restriction. Do not
expose robot RPC ports or modify Mac network settings for this deployment.

Open the setup page, explicitly check the selected model, choose tools and save
parameters. The command is prepared in the console; sending it starts the task.
`finish` is required. Only native tools have an executor in this integration;
unsupported generated tool selections fail before ENV startup. Original CLI and
Flash paths retain their registration when no Workbench selection is supplied.

Run history preserves the actual task/configuration, official success availability,
stop reason, model/tool events, token usage and three camera videos. Videos use
H.264 and browser-compatible MP4 indexing. A successful component test or model
`finish` is not evidence of official task success.
