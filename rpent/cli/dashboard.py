# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""CLI orchestration for one long-lived Dashboard Session."""

from __future__ import annotations

import argparse
import copy
import json
import shlex
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rpent.cli.main import (
    _handoff_message,
    _serialize_messages,
)
from rpent.dashboard.events import RunStartedEvent
from rpent.evaluation import RunFinalizationContext
from rpent.memory import MemoryManager
from rpent.planner.base import build_planner
from rpent.robots import get_toolkit
from rpent.utils.config import get_memory_dir
from rpent.utils.logging import get_logger, init_output_dir

if TYPE_CHECKING:
    from rpent.dashboard.state import ClaimedTask, DashboardState
    from rpent.robots.robot_spec import RobotSpec
    from rpent.utils.daemon import ProcessDaemon

logger = get_logger("agent")


def run_dashboard_session(
    args: argparse.Namespace,
    robot_spec: RobotSpec,
    *,
    parser: argparse.ArgumentParser,
) -> int:
    """Run one long-lived Dashboard Session with sequential fresh TaskRuns."""
    if (
        robot_spec.is_real_robot
        and not (robot_spec.dashboard or {}).get("external_env", False)
        and not robot_spec.supports_human_interactive_exploration
    ):
        parser.error(
            "Physical Dashboard control requires a robot runtime with human confirmation."
        )
    from rpent.dashboard.server import DashboardServer
    from rpent.dashboard.session import DashboardSessionController
    from rpent.dashboard.state import DashboardState
    from rpent.utils.config import get_repo_root

    dashboard_spec = robot_spec.dashboard
    if dashboard_spec is None:
        parser.error(f"robot {robot_spec.name!r} does not support Dashboard control")
    runtime_components = tuple(
        component
        for component in dashboard_spec["runtime_components"]
        if not component.get("planners") or args.planner in component["planners"]
    )
    dashboard_spec = {**dashboard_spec, "runtime_components": runtime_components}
    shared_components = {
        component["name"]
        for component in runtime_components
        if component["scope"] == "shared"
    }
    unique_components = {
        component["name"]
        for component in runtime_components
        if component["scope"] == "unique"
    }

    if getattr(args, "env_endpoint", None) is not None and not (
        dashboard_spec.get("external_env", False)
        or (
            robot_spec.is_real_robot
            and robot_spec.supports_human_interactive_exploration
        )
    ):
        parser.error(
            "Dashboard task control cannot use --env-endpoint because each "
            "TaskRun requires a fresh owned env_server"
        )
    if dashboard_spec.get("external_env", False) and not getattr(
        args, "env_endpoint", None
    ):
        parser.error(
            "--env-endpoint is required for this external-environment Dashboard"
        )
    if args.planner == "api" and not args.model:
        parser.error("--model is required when --planner=api")

    if args.output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H:%M:%S")
        session_root = get_repo_root() / "logs" / f"{timestamp}_dashboard_session"
    else:
        session_root = Path(args.output_dir)
    session_root = init_output_dir(session_root, verbose=args.verbose)
    logger.info("physical agent cmd: %s", shlex.join([sys.executable, *sys.argv]))

    state = DashboardState(
        output_dir=session_root,
        dashboard_spec=dashboard_spec,
    )
    from rpent.dashboard.workbench import Workbench

    state.workbench = Workbench.from_env(robot=robot_spec.name)
    if state.workbench is not None:
        if robot_spec.name == "flexiv":
            state.workbench.config["control_mode"] = getattr(
                args, "control_mode", "native"
            )
        state.workbench.recover_interrupted()
        if getattr(args, "pilot_root", None):
            state.workbench.bind_pilot(
                args.pilot_root,
                args.pilot_cell,
                freeze_id=args.pilot_freeze,
                run_options={
                    "max_turns": args.max_turns,
                    "max_tokens": args.max_tokens,
                    "planner_timeout_s": args.planner_timeout_s,
                },
            )
    dashboard_server = DashboardServer(
        host=args.dashboard_host,
        port=args.dashboard_port,
        language=args.dashboard_language,
        state=state,
        planner=args.planner,
        model=args.model,
        base_url=args.base_url,
        robot_name=robot_spec.name,
        run_options={
            "max_turns": args.max_turns,
            "max_tokens": args.max_tokens,
            "planner_timeout_s": args.planner_timeout_s,
            **(
                {"control_mode": getattr(args, "control_mode", "native")}
                if robot_spec.name == "flexiv"
                else {}
            ),
        },
    )
    dashboard_url = dashboard_server.start()
    print(f"Dashboard: {dashboard_url}", flush=True)
    logger.info("Dashboard: %s", dashboard_url)

    # Shared robot services may validate memory before a task is claimed.
    # Robots with a preparation hook select memory at each task boundary instead.
    if (
        robot_spec.prepare_memory is None
        and not getattr(args, "explore", False)
        and getattr(args, "memory_profile", "hf") == "hf"
    ):
        MemoryManager(get_memory_dir(robot_spec.name)).sync(
            remote_repo=robot_spec.memory_repo_id,
        )

    controller = DashboardSessionController(
        state=state,
        start_shared=lambda: robot_spec.init_runtime(
            args,
            session_root,
            state,
            shared_components,
        ),
        run_task=lambda claimed, shared: _run_dashboard_task(
            args=args,
            robot_spec=robot_spec,
            state=state,
            claimed=claimed,
            shared_runtime_kwargs=shared,
            unique_components=unique_components,
            session_root=session_root,
        ),
    )
    try:
        controller.run()
        if state.session_state == "fatal":
            logger.error(
                "Dashboard Session is fatal. Still serving at %s; "
                "press Ctrl+C to stop.",
                dashboard_url,
            )
            threading.Event().wait()
    except KeyboardInterrupt:
        state.request_shutdown()
    return 0


def _run_dashboard_task(*, args, robot_spec, state, claimed, **kwargs):
    if getattr(state, "workbench", None) is None:
        return _run_dashboard_task_inner(
            args=args, robot_spec=robot_spec, state=state, claimed=claimed, **kwargs
        )
    from rpent.dashboard.workbench import (
        source_snapshot,
        stamp,
        termination_reason,
        write_json,
    )
    from rpent.utils.config import get_repo_root

    selected = claimed.request["frozen_tools"]
    profile_id = claimed.request["model_profile"]
    with state.workbench.environment(profile_id) as profile:
        configured = copy.copy(args)
        for key in ("planner", "model", "base_url", "reasoning_effort"):
            setattr(configured, key, profile.get(key))
        error = None
        try:
            state.workbench.validate_pilot_request(claimed.request)
            write_json(
                claimed.output_dir / "dashboard_config.json",
                {
                    "robot": robot_spec.name,
                    "model": configured.model,
                    "task": {
                        k: v for k, v in claimed.request.items() if k != "frozen_tools"
                    },
                },
            )
            manifest = {
                "run_id": state.run_id,
                "started_at": stamp(),
                "profile": {
                    k: profile.get(k)
                    for k in ("id", "planner", "model", "reasoning_effort", "base_url")
                },
                "tools": selected,
                "task": {
                    k: v for k, v in claimed.request.items() if k != "frozen_tools"
                },
                "code": source_snapshot(get_repo_root(), claimed.output_dir),
            }
            write_json(claimed.output_dir / "manifest.json", manifest)
            error = _run_dashboard_task_inner(
                args=configured,
                robot_spec=robot_spec,
                state=state,
                claimed=claimed,
                **kwargs,
            )
            return error
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            state.journal.append("run_end", {"error": error})
            # Inner finalization saves detailed outcome; retain startup failures too.
            if not (claimed.output_dir / "outcome.json").exists():
                write_json(
                    claimed.output_dir / "outcome.json",
                    {
                        "ended_at": stamp(),
                        "error": error,
                        "status": termination_reason(
                            error, state.workbench_aborted, None, False
                        ),
                        "environment_success": None,
                    },
                )
            if (claimed.output_dir / "pilot-attempt.json").exists():
                from robots.univtac.pilot.execution import restore_from_output

                restore_from_output(claimed.output_dir).after_finish(
                    json.loads((claimed.output_dir / "outcome.json").read_text())
                )


def _run_dashboard_task_inner(
    *,
    args: argparse.Namespace,
    robot_spec: RobotSpec,
    state: DashboardState,
    claimed: ClaimedTask,
    shared_runtime_kwargs: dict[str, Any],
    unique_components: set[str],
    session_root: Path,
) -> str | None:
    """Execute one fresh Dashboard TaskRun against Session-owned services."""
    human_interactive_run = (
        robot_spec.is_real_robot and robot_spec.supports_human_interactive_exploration
    )
    task_args = copy.copy(args)
    for name, value in claimed.request.items():
        setattr(task_args, name, value)
    if task_args.explore and not robot_spec.supports_exploration:
        raise ValueError(f"--explore is not supported for robot {robot_spec.name!r}")
    task_args.output_dir = str(claimed.output_dir)
    claimed.output_dir.mkdir(parents=True, exist_ok=True)
    (claimed.output_dir / "dashboard_config.json").write_text(
        json.dumps(
            {
                "robot": robot_spec.name,
                "task": {
                    k: v for k, v in claimed.request.items() if k != "frozen_tools"
                },
                "model": task_args.model,
                **{
                    name: value
                    for name, value in vars(task_args).items()
                    if name in {"max_turns", "max_tokens", "planner_timeout_s"}
                },
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    run_config = robot_spec.parse_config(task_args)
    if getattr(state, "workbench", None) is not None:
        run_config.prompt_vars["manual_tools"] = claimed.request["frozen_tools"]
        run_config.prompt_vars["run_journal"] = state.journal
    from rpent.memory.loading import prepare_run_memory

    prepare_run_memory(task_args, robot_spec, run_config)
    if getattr(state, "workbench", None) is not None:
        material_root = state.workbench.config.get("language_materials")
        if material_root and robot_spec.name == "libero":
            from robots.libero.research.language_materials import freeze_materials

            freeze_materials(
                material_root, run_config.output_dir, run_config.prompt_vars
            )
    output_dir = init_output_dir(run_config.output_dir, verbose=args.verbose)

    recipe_tag = run_config.recipe_tag
    finish_result = None
    messages: list[dict] = []
    stats: dict = {}
    agent_error: str | None = None
    task_daemons: list[ProcessDaemon] = []
    recipe_path = ""
    started = time.time()
    solved = False
    memory_manager = None
    environment_success = None
    try:
        task_daemons, task_runtime_kwargs = robot_spec.init_runtime(
            task_args,
            output_dir,
            state,
            unique_components,
        )
        if not state.task_replacement_requested:
            runtime_kwargs = {
                **task_runtime_kwargs,
                **shared_runtime_kwargs,
            }
            prompt_vars = {**run_config.prompt_vars, "output_dir": output_dir}
            session_message = robot_spec.prompts.render("user", variables=prompt_vars)
            sessions = max(
                1,
                int(getattr(task_args, "explore_sessions", 1) or 1),
            )
            if not getattr(task_args, "explore", False):
                sessions = 1
            if not state.task_replacement_requested:
                state.emit(RunStartedEvent())
            for session_number in range(1, sessions + 1):
                if (
                    state.task_replacement_requested
                    or state.task_finalization_cancelled
                ):
                    break
                if session_number > 1:
                    logger.info(
                        "=== handing off to agent %d/%d ===",
                        session_number,
                        sessions,
                    )
                    session_message = _handoff_message(
                        output_dir,
                        session_number,
                        sessions,
                        robot_name=args.robot_name,
                    )
                system_prompt = robot_spec.prompts.render(
                    "system",
                    variables={
                        **prompt_vars,
                        "session_number": session_number,
                        "session_max": sessions,
                    },
                )
                state_output_dir = output_dir
                if getattr(task_args, "explore", False):
                    state_output_dir = (
                        output_dir / "sessions" / f"session_{session_number:03d}"
                    )
                    state.begin_planner_session(
                        video_path=state_output_dir / "episode.mp4",
                    )
                if robot_spec.supports_exploration:
                    operator_kwargs = {}
                    if human_interactive_run:
                        from rpent.tools.human_in_the_loop import HumanInTheLoopInput

                        state.operator_exploration = bool(task_args.explore)
                        state.operator = HumanInTheLoopInput(
                            interactive=True, on_change=state.operator_changed
                        )
                        operator_kwargs["operator_input"] = state.operator
                    toolkit = get_toolkit(
                        args.robot_name,
                        runtime_kwargs=runtime_kwargs,
                        dashboard_events=state,
                        config=run_config,
                        mode="exploration" if task_args.explore else "evaluation",
                        attempts_per_session=getattr(
                            task_args, "explore_attempts_per_session", 0
                        ),
                        state_output_dir=state_output_dir,
                        **operator_kwargs,
                    )
                else:
                    toolkit = get_toolkit(
                        args.robot_name,
                        runtime_kwargs=runtime_kwargs,
                        dashboard_events=state,
                        config=run_config,
                    )
                solved = False
                if getattr(state, "workbench", None) is not None:
                    from robots.libero.research.manual import availability_prompt
                    from rpent.dashboard.workbench import write_json

                    # UniVTAC renders its frozen selection inside its PromptBundle.
                    # Legacy guides still need the selection override.
                    if args.robot_name != "univtac":
                        system_prompt = (
                            availability_prompt(claimed.request["frozen_tools"])
                            + system_prompt
                        )
                    write_json(
                        Path(output_dir) / "prompts.json",
                        {"system": system_prompt, "user": session_message},
                    )
                    write_json(
                        Path(output_dir) / "tool-declarations.json",
                        [
                            {
                                "name": t.name,
                                "description": t.description,
                                "parameters": t.input_schema,
                            }
                            for t in toolkit.list_tools()
                        ],
                    )
                state.bind_toolkit(toolkit)
                memory_manager = toolkit.memory
                try:
                    planner = build_planner(
                        task_args.planner,
                        output_dir=output_dir,
                        recipe_tag=recipe_tag,
                        robot_name=args.robot_name,
                        base_url=task_args.base_url,
                        model=task_args.model,
                        memory_dir=run_config.prompt_vars.get("memory_dir"),
                        max_tokens=task_args.max_tokens,
                        planner_timeout_s=task_args.planner_timeout_s,
                        reasoning_effort=task_args.reasoning_effort,
                        claude_code_max_budget_usd=args.claude_code_max_budget_usd,
                        dashboard_events=state,
                        no_images=args.no_images,
                    )
                    result = planner.solve(
                        system_prompt=system_prompt,
                        user_message=session_message,
                        toolkit=toolkit,
                        max_turns=task_args.max_turns,
                        dashboard_interaction=state,
                    )
                    finish_result = result.finish_result
                    messages += result.messages
                    stats = result.stats
                    agent_error = result.error
                    if human_interactive_run and toolkit.direct_verdict_requested:
                        finish_result = toolkit.finalize_direct_verdict()
                        if agent_error:
                            stats["planner_error_at_operator_verdict"] = agent_error
                    if robot_spec.supports_exploration:
                        solved = bool(toolkit.solved())
                        if solved:
                            recipe_path = (
                                toolkit.write_recipe(recipe_tag) or recipe_path
                            )
                finally:
                    try:
                        state.unbind_toolkit(toolkit)
                        if robot_spec.finalize_run is not None:
                            environment_success = bool(toolkit.solved())
                            solved = environment_success
                    finally:
                        toolkit.close()
                if (
                    solved
                    or state.task_replacement_requested
                    or (finish_result or {}).get("operator_finished")
                ):
                    break
                if agent_error:
                    if session_number < sessions and "timed out" in agent_error.lower():
                        logger.warning(
                            "session %d/%d timed out; continuing with a fresh handoff",
                            session_number,
                            sessions,
                        )
                        continue
                    break
    except KeyboardInterrupt:
        state.request_shutdown()
        agent_error = "Dashboard interrupted by operator."
    except Exception as exc:
        logger.error("EXCEPTION in Dashboard TaskRun %04d: %s", claimed.number, exc)
        agent_error = str(exc)
    finally:
        if human_interactive_run and state.operator is not None:
            state.operator.close()
            state.operator = None
        cleanup_errors: list[str] = []
        if recipe_path:
            logger.info("recipe: %s", recipe_path)
        else:
            logger.info("recipe: not written (cell unsolved)")
        for daemon in reversed(task_daemons):
            try:
                daemon.stop()
            except Exception as exc:
                cleanup_errors.append(f"robot cleanup failed: {exc}")
        if cleanup_errors:
            cleanup_error = "; ".join(cleanup_errors)
            if agent_error is None:
                agent_error = cleanup_error
            else:
                logger.warning("%s", cleanup_error)

        transcript_path = output_dir / f"transcript_{run_config.recipe_tag}.json"
        record = {
            **run_config.task_desc,
            "model": task_args.model,
            "elapsed_s": round(time.time() - started, 1),
            "finish": finish_result,
            "environment_success": environment_success,
            "stats": stats,
            "messages": _serialize_messages(messages),
            "error": agent_error,
        }
        if getattr(state, "workbench", None) is not None:
            from rpent.dashboard.workbench import (
                clean,
                stamp,
                termination_reason,
                write_json,
            )

            record = clean(record)
            observed_steps = (
                toolkit.state.records() if memory_manager is not None else []
            )
            calls = [r.command for r in observed_steps if r.command]
            write_json(
                Path(output_dir) / "outcome.json",
                {
                    "ended_at": stamp(),
                    "environment_success": environment_success,
                    "finish": finish_result,
                    "error": agent_error,
                    "stats": stats,
                    "elapsed_s": record["elapsed_s"],
                    "status": termination_reason(
                        agent_error, state.workbench_aborted, finish_result, solved
                    ),
                    "last_completed_step": toolkit.state.records()[-1].step_idx
                    if calls
                    else 0,
                    "actions": len(calls),
                    "release_count": sum(c.get("action") == "release" for c in calls),
                    "release_evidence": [
                        {
                            "step": r.step_idx,
                            "command": r.command,
                            "result": r.result,
                            "gripper_qpos": r.state.get("robot0_gripper_qpos"),
                        }
                        for r in observed_steps
                        if (r.command or {}).get("action") == "release"
                    ],
                    "last_gripper_qpos": observed_steps[-1].state.get(
                        "robot0_gripper_qpos"
                    )
                    if observed_steps
                    else None,
                    "video_recorded": (Path(output_dir) / "episode.mp4").is_file(),
                    "stable_placement": "未独立验证",
                },
            )
        try:
            with open(transcript_path, "a") as transcript_file:
                json.dump(record, transcript_file, indent=2, default=str)
        except Exception as exc:
            logger.warning(
                "failed to write TaskRun transcript %s: %s", transcript_path, exc
            )
        init_output_dir(session_root, verbose=args.verbose)

    if (
        getattr(task_args, "explore", False)
        and getattr(task_args, "auto_merge_memory", False)
        and not agent_error
        and not state.task_finalization_cancelled
        and memory_manager is not None
    ):
        try:
            merge_result = memory_manager.merge_memory(
                cell_tag=run_config.recipe_tag,
                run_state_dir=run_config.output_dir,
                solved=solved,
            )
            if merge_result:
                logger.info("run finalized: %s", merge_result)
        except Exception as exc:
            warning = f"memory finalization failed: {type(exc).__name__}: {exc}"
            logger.warning("%s", warning)
            state.report_task_warning(warning)

    if robot_spec.finalize_run is not None:
        try:
            robot_spec.finalize_run(
                RunFinalizationContext(
                    output_dir=Path(output_dir),
                    robot_name=robot_spec.name,
                    task_desc=dict(run_config.task_desc),
                    environment_success=environment_success,
                    agent_error=agent_error,
                    elapsed_s=time.time() - started,
                    planner=args.planner,
                    model=task_args.model,
                    reasoning_effort=args.reasoning_effort,
                    max_turns=task_args.max_turns,
                    planner_timeout_s=task_args.planner_timeout_s,
                    finish_result=dict(finish_result)
                    if finish_result is not None
                    else None,
                    stats=dict(stats),
                )
            )
        except Exception as exc:
            finalization_error = (
                f"result finalization failed: {type(exc).__name__}: {exc}"
            )
            if agent_error:
                logger.warning("%s", finalization_error)
            else:
                agent_error = finalization_error
    return agent_error
