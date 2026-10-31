# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""UniVTAC registration using RPent planners, dashboard and state storage."""

import argparse
import contextlib
import json
import uuid
from datetime import datetime
from pathlib import Path

from robots.univtac.instructions import SEEN_INSTRUCTIONS
from robots.univtac.prompt_bundle import system_prompt, user_prompt
from rpent.memory import MemoryManager
from rpent.robots.prompt_bundle import PromptBundle
from rpent.robots.robot_spec import RobotSpec, RunConfig
from rpent.robots.runtime import stop_owned_daemons, try_spawn_server, try_wait_server
from rpent.utils.config import get_repo_root
from rpent.utils.daemon import ProcessDaemon, pick_free_port
from rpent.utils.rpc.http_rpc import HttpRpcClient

TASKS = ("insert_hole", "insert_tube", "pull_out_key")
DASHBOARD_SPEC = {
    "task": {
        "command": "/rpent-task",
        "usage": "/rpent-task univtac <task> <seed>",
        "fields": (
            {"name": "suite", "suggestions": ("univtac",)},
            {"name": "task", "kind": "integer", "minimum": 0},
            {"name": "seed", "kind": "integer", "minimum": 0},
        ),
        "display": "UniVTAC / task {task} / seed {seed}",
        "output_slug": "univtac_t{task}_s{seed}",
    },
    "runtime_components": ({"name": "env", "label": "UniVTAC", "scope": "unique"},),
    "primitives": ("move_eef",),
}


def get_robot_spec() -> RobotSpec:
    return RobotSpec(
        name="univtac",
        prompts=PromptBundle(system=system_prompt, user=user_prompt),
        add_cli_args=_add_cli_args,
        parse_config=_parse_config,
        init_runtime=_init_runtime,
        dashboard=DASHBOARD_SPEC,
        prepare_memory=_prepare_memory,
        finalize_run=_finalize_run,
        validate_args=_validate_args,
    )


def _add_cli_args(parser: argparse.ArgumentParser, use_dashboard: bool) -> None:
    parser.set_defaults(max_turns=60, planner_timeout_s=3600)
    parser.add_argument("--env-endpoint")
    parser.add_argument("--univtac-root", help="Pinned external UniVTAC checkout")
    parser.add_argument(
        "--univtac-python", help="Independent simulator Python executable"
    )
    parser.add_argument("--suite", choices=("univtac",), default="univtac")
    parser.add_argument("--task", type=int, choices=range(len(TASKS)), default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pilot-root", help="Existing bounded pilot ledger directory")
    parser.add_argument(
        "--pilot-cell", help="Reserve one protocol cell before starting"
    )
    parser.add_argument(
        "--pilot-freeze", help="Frozen bundle ID for validation/holdout"
    )
    parser.add_argument(
        "--tool-selection-json",
        help="Explicit frozen tool declarations for CLI evaluation",
    )


def _validate_args(args) -> None:
    if not args.env_endpoint and not (args.univtac_root and args.univtac_python):
        raise ValueError(
            "Provide --univtac-root and --univtac-python, or a borrowed --env-endpoint"
        )
    if bool(args.pilot_root) != bool(args.pilot_cell):
        raise ValueError("--pilot-root and --pilot-cell must be provided together")
    if args.pilot_freeze and not args.pilot_root:
        raise ValueError("--pilot-freeze requires --pilot-root")
    if args.pilot_root and args.env_endpoint:
        raise ValueError(
            "Pilot runs require an owned fresh simulator process; remove --env-endpoint"
        )


def _parse_config(args) -> RunConfig:
    if args.seed < 0:
        raise ValueError("seed must be nonnegative")
    task_name = TASKS[args.task]
    output = Path(
        args.output_dir
        or get_repo_root()
        / "logs"
        / (datetime.now().strftime("%Y%m%d-%H%M%S_univtac_") + uuid.uuid4().hex[:8])
    )
    return RunConfig(
        recipe_tag=f"univtac_{task_name}_s{args.seed}",
        output_dir=output,
        prompt_vars={
            "instruction": SEEN_INSTRUCTIONS[task_name],
            "task_guidance": "",
            "task_name": task_name,
            "seed": args.seed,
        },
        task_desc={
            "suite": "univtac",
            "task": args.task,
            "task_name": task_name,
            "seed": args.seed,
        },
    )


def _prepare_memory(args, config) -> None:
    try:
        _prepare_run(args, config)
    except Exception as exc:
        from robots.univtac.pilot.execution import restore_from_output
        from rpent.dashboard.workbench import write_json

        execution = restore_from_output(config.output_dir)
        if execution is not None:
            result = execution.after_finish(
                {
                    "termination_reason": "setup_failure",
                    "error": str(exc),
                    "environment_success": None,
                }
            )
            write_json(config.output_dir / "outcome.json", result)
        raise


def _prepare_run(args, config) -> None:
    # No cross-task memory download or writes during paired evaluation.
    config.prompt_vars["memory_dir"] = config.output_dir / "empty-memory"
    if getattr(args, "tool_selection_json", None):
        if "manual_tools" in config.prompt_vars:
            raise ValueError(
                "Use the dashboard selection or --tool-selection-json, not both"
            )
        config.prompt_vars["manual_tools"] = json.loads(
            Path(args.tool_selection_json).read_text()
        )
    if getattr(args, "pilot_root", None):
        from robots.univtac.pilot.execution import before_start
        from robots.univtac.pilot.provenance import collect

        execution = before_start(
            args.pilot_root,
            args.pilot_cell,
            config.output_dir,
            model=args.model.removeprefix("openai-chat:"),
            task=config.task_desc["task_name"],
            seed=args.seed,
            selected=config.prompt_vars.get("manual_tools"),
            budget={
                "max_turns": args.max_turns,
                "planner_timeout_s": args.planner_timeout_s,
                "model_request_timeout_s": 300,
            },
            freeze_id=args.pilot_freeze,
            model_profile_settings={
                key: getattr(args, key, None)
                for key in (
                    "planner",
                    "model",
                    "reasoning_effort",
                    "base_url",
                    "max_tokens",
                )
            },
            actual_evidence=collect(),
        )
        config.prompt_vars["manual_tools"] = execution.selected
        config.prompt_vars["task_guidance"] = execution.guidance
        config.prompt_vars["sandbox_image"] = execution.sandbox_image
    from robots.univtac.toolkit import native_catalog, validate_selection
    from rpent.dashboard.workbench import RunJournal, source_snapshot, stamp, write_json

    selected = config.prompt_vars.setdefault("manual_tools", native_catalog())
    validate_selection(selected)
    config.prompt_vars.setdefault("run_journal", RunJournal(config.output_dir))
    path = config.output_dir / "manifest.json"
    if not path.exists():
        write_json(
            path,
            {
                "started_at": stamp(),
                "robot": "univtac",
                "task": config.task_desc,
                "tools": selected,
                "code": source_snapshot(get_repo_root(), config.output_dir),
                "profile": {
                    key: getattr(args, key, None)
                    for key in (
                        "planner",
                        "model",
                        "reasoning_effort",
                        "base_url",
                        "max_tokens",
                    )
                },
                "budget": {
                    "max_turns": args.max_turns,
                    "planner_timeout_s": args.planner_timeout_s,
                    "model_request_timeout_s": 300,
                },
                "memory": "empty/read_only",
            },
        )
        write_json(
            config.output_dir / "dashboard_config.json",
            {"robot": "univtac", "task": config.task_desc, "model": args.model},
        )
    variables = {**config.prompt_vars, "output_dir": config.output_dir}
    prompts = get_robot_spec().prompts
    write_json(
        config.output_dir / "prompts.json",
        {
            "system": prompts.render("system", variables=variables),
            "user": prompts.render("user", variables=variables),
        },
    )


def _init_runtime(args, output_dir, dashboard_events, components=None):
    from robots.univtac.env_client import UniVTACEnvClient

    if components is not None and "env" not in components:
        return [], {}
    owned = {}

    def spawn():
        if args.env_endpoint:
            return None, HttpRpcClient(args.env_endpoint)
        port = pick_free_port()
        daemon = ProcessDaemon(
            name="univtac_env_server",
            cmd=[
                args.univtac_python,
                "-m",
                "robots.univtac.env_server",
                "--root",
                args.univtac_root,
                "--output-dir",
                str(output_dir / "native"),
                "--task-name",
                TASKS[args.task],
                "--seed",
                str(args.seed),
                "--port",
                str(port),
                "--transport",
                "http",
                "--parent-watch",
            ],
            log_path=str(output_dir / "univtac_env_server.log"),
            env_overrides={"OMNI_KIT_ACCEPT_EULA": "YES"},
        )
        daemon.start()
        return daemon, HttpRpcClient(f"http://127.0.0.1:{port}")

    def connect():
        from robots.univtac.pilot.execution import restore_from_output

        env = UniVTACEnvClient(rpc, task_name=TASKS[args.task], seed=args.seed)
        execution = restore_from_output(output_dir)
        if execution is not None:
            try:
                execution.after_reset(env.evaluator_state())
            except Exception:
                with contextlib.suppress(Exception):
                    env.close()
                raise
        return env

    try:
        daemon, rpc = try_spawn_server(owned, dashboard_events, "env", spawn)
        env = try_wait_server(
            owned,
            dashboard_events,
            "env",
            rpc,
            daemon,
            300,
            post_fn=connect,
        )
    except (Exception, KeyboardInterrupt) as exc:
        from robots.univtac.pilot.execution import restore_from_output
        from rpent.dashboard.workbench import write_json

        stop_owned_daemons(owned, dashboard_events)
        result = {
            "termination_reason": "aborted"
            if isinstance(exc, KeyboardInterrupt)
            else "setup_failure",
            "error": f"{type(exc).__name__}: {exc}",
            "environment_success": None,
        }
        execution = restore_from_output(output_dir)
        if execution is not None:
            result = execution.after_finish(result)
        write_json(output_dir / "outcome.json", result)
        raise
    return list(owned.values()), {"env": env}


def get_toolkit(*, runtime_kwargs, dashboard_events, config):
    from robots.univtac.toolkit import UniVTACToolkit

    toolkit = UniVTACToolkit(
        env=runtime_kwargs["env"],
        output_dir=config.output_dir,
        dashboard_events=dashboard_events,
        memory=MemoryManager(
            config.output_dir / "empty-memory", memory_access="read_only"
        ),
        selected=config.prompt_vars.get("manual_tools"),
        journal=config.prompt_vars.get("run_journal"),
        sandbox_image=config.prompt_vars.get("sandbox_image", "embodied-sensor:pilot"),
    )
    from rpent.dashboard.workbench import write_json

    write_json(
        config.output_dir / "tool-declarations.json",
        [
            {
                "name": item.name,
                "description": item.description,
                "parameters": item.input_schema,
            }
            for item in toolkit.list_tools()
        ],
    )
    return toolkit


def _finalize_run(context):
    from rpent.dashboard.workbench import termination_reason, write_json

    path = context.output_dir / "outcome.json"
    result = json.loads(path.read_text()) if path.exists() else {}
    result.update(
        environment_success=context.environment_success,
        success_protocol="UniVTAC official evaluator; no release requirement",
        release_required=False,
    )
    for name in ("agent_error", "elapsed_s", "stats", "finish_result"):
        key = {"agent_error": "error", "finish_result": "finish"}.get(name, name)
        result.setdefault(key, getattr(context, name, None))
    result.setdefault(
        "status",
        termination_reason(
            result.get("error"),
            False,
            result.get("finish"),
            context.environment_success,
        ),
    )
    for key in (
        "stable_placement",
        "release_count",
        "release_evidence",
        "last_gripper_qpos",
    ):
        result.pop(key, None)
    from robots.univtac.pilot.execution import restore_from_output

    execution = restore_from_output(context.output_dir)
    if execution is not None:
        if "outcome" not in execution.record and execution.record["cell"]["stage"] in {
            "explore",
            "provisional",
        }:
            from robots.univtac.pilot.evidence import export_development

            try:
                result["maker_inputs"] = export_development(context.output_dir)
            except (OSError, ValueError) as exc:
                result["maker_export_error"] = f"{type(exc).__name__}: {exc}"
        write_json(path, result)
        execution.after_finish(result)
    else:
        write_json(path, result)
    return path
