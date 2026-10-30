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

"""Register a single-arm Flexiv with collector or direct RDK control."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from robots.flexiv.prompt_bundle import system_prompt, user_prompt
from rpent.memory import MemoryManager
from rpent.robots.prompt_bundle import PromptBundle
from rpent.robots.robot_spec import RobotSpec, RunConfig
from rpent.robots.runtime import try_spawn_server, try_wait_server
from rpent.utils.config import get_memory_dir, get_repo_root
from rpent.utils.daemon import ProcessDaemon, pick_free_port
from rpent.utils.rpc.http_rpc import HttpRpcClient

INSPECTION = "检查机械臂连接、关节角、TCP和相机状态，不要移动机械臂。"
DASHBOARD_SPEC = {
    "external_env": True,
    "task": {
        "command": "/rpent-task",
        "usage": '/rpent-task "<instruction>"',
        "fields": ({"name": "instruction", "suggestions": (INSPECTION,)},),
        "display": "Flexiv: {instruction}",
        "output_slug": "flexiv",
    },
    "runtime_components": (
        {"name": "env", "label": "Flexiv Environment", "scope": "unique"},
    ),
    "primitives": (
        "observe",
        "reset_home",
        "move_delta",
        "move_tcp",
        "move_eef",
        "move_eef_delta",
        "align_tool_down",
        "set_gripper",
        "stop_motion",
    ),
}


def get_robot_spec():
    return RobotSpec(
        name="flexiv",
        prompts=PromptBundle(system=system_prompt, user=user_prompt),
        add_cli_args=_add_cli_args,
        parse_config=_parse_config,
        init_runtime=_init_runtime,
        dashboard=DASHBOARD_SPEC,
        is_real_robot=True,
        prepare_memory=_prepare_memory,
    )


def _prepare_memory(args, config):
    """Use local Flexiv memory; never download another embodiment's recipes."""
    config.prompt_vars["memory_dir"] = get_memory_dir("flexiv")


def _add_cli_args(parser: argparse.ArgumentParser, use_dashboard: bool):
    parser.add_argument("--env-endpoint", default=None)
    parser.add_argument("--collector-endpoint", default="http://127.0.0.1:9527")
    parser.add_argument("--rdk-endpoint", default="http://127.0.0.1:5000")
    parser.add_argument("--instruction", default=INSPECTION)
    parser.add_argument(
        "--control-mode",
        choices=("native", "eef_delta", "rdk"),
        default="native",
        help="Flexiv task tools and prompt; rdk uses the independent RDK HTTP server.",
    )


def _parse_config(args):
    instruction = args.instruction.strip()
    if not instruction:
        raise ValueError("An instruction is required")
    output = Path(
        args.output_dir
        or get_repo_root()
        / "logs"
        / (datetime.now().strftime("%Y%m%d-%H%M%S") + "_flexiv")
    )
    control_mode = getattr(args, "control_mode", "native")
    if control_mode not in ("native", "eef_delta", "rdk"):
        raise ValueError("Unknown Flexiv control mode")
    return RunConfig(
        recipe_tag="flexiv",
        output_dir=output,
        prompt_vars={"instruction": instruction, "control_mode": control_mode},
        task_desc={"instruction": instruction, "control_mode": control_mode},
    )


def get_toolkit(*, runtime_kwargs, dashboard_events, config):
    from robots.flexiv.toolkit import FlexivToolkit

    toolkit_class, options = FlexivToolkit, {}
    if "manual_tools" in config.prompt_vars:
        from robots.flexiv.manual import ManualToolkit

        toolkit_class = ManualToolkit
        options = {
            "selected": config.prompt_vars["manual_tools"],
            "journal": config.prompt_vars.get("run_journal"),
        }
    try:
        return toolkit_class(
            env=runtime_kwargs["env"],
            output_dir=config.output_dir,
            dashboard_events=dashboard_events,
            control_mode=config.prompt_vars.get("control_mode", "native"),
            memory=MemoryManager(
                root=get_memory_dir("flexiv"), memory_access="read_only"
            ),
            **options,
        )
    except Exception:
        runtime_kwargs["env"].close()
        raise


def _init_runtime(args, output_dir, dashboard_events, components=None):
    from robots.flexiv.env_client import FlexivEnvClient

    if components is not None and "env" not in components:
        return [], {}
    owned = {}

    def spawn():
        if args.env_endpoint:
            return None, HttpRpcClient(args.env_endpoint)
        port = pick_free_port()
        backend_args = (
            ["--backend", "rdk", "--rdk-endpoint", args.rdk_endpoint]
            if getattr(args, "control_mode", "native") == "rdk"
            else ["--collector-endpoint", args.collector_endpoint]
        )
        daemon = ProcessDaemon(
            name="flexiv_env_server",
            cmd=[
                sys.executable,
                "-m",
                "robots.flexiv.env_server",
                "--port",
                str(port),
                *backend_args,
            ],
            log_path=str(output_dir / "flexiv_env_server.log"),
        )
        daemon.start()
        return daemon, HttpRpcClient(f"http://127.0.0.1:{port}")

    daemon, rpc = try_spawn_server(owned, dashboard_events, "env", spawn)
    env = try_wait_server(
        owned,
        dashboard_events,
        "env",
        rpc,
        daemon,
        60,
        post_fn=lambda: FlexivEnvClient(rpc),
    )
    return list(owned.values()), {"env": env}
