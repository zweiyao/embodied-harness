# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Manual experiment catalog, immutable selections and durable run evidence."""

from __future__ import annotations

import base64
import copy
import dataclasses
import difflib
import hashlib
import inspect
import json
import os
import re
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    if isinstance(value, dict):
        return {
            str(k): (
                "[redacted]"
                if re.search(
                    r"api.?key$|authorization|access_token|refresh_token|id_token|password",
                    str(k),
                    re.I,
                )
                else clean(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, str):
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
            secret = os.environ.get(key)
            if secret and len(secret) > 8:
                value = value.replace(secret, "[redacted]")
        return re.sub(
            r"\bsk-[A-Za-z0-9_.-]+|Bearer\s+[A-Za-z0-9_.-]+", "[redacted]", value
        )
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(clean(value), ensure_ascii=False, indent=2, default=str) + "\n"
    )
    temp.replace(path)


class RunJournal:
    """Flush events before returning; binary model inputs are content-addressed."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def encode(self, value):
        if isinstance(value, bytes):
            name = "inputs/" + hashlib.sha256(value).hexdigest() + ".bin"
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            if not path.exists():
                path.write_bytes(value)
            return {"artifact": name, "bytes": len(value)}
        if (
            isinstance(value, str)
            and value.startswith("data:image/")
            and ";base64," in value
        ):
            return {
                "media_type": value.split(";")[0][5:],
                **self.encode(base64.b64decode(value.split(",", 1)[1])),
            }
        if dataclasses.is_dataclass(value):
            return {
                f.name: self.encode(getattr(value, f.name))
                for f in dataclasses.fields(value)
            }
        if hasattr(value, "model_dump"):
            return self.encode(value.model_dump(mode="python"))
        if isinstance(value, dict):
            if value.get("type") == "image" and isinstance(value.get("data"), str):
                return {
                    "type": "image",
                    "mimeType": value.get("mimeType"),
                    **self.encode(base64.b64decode(value["data"])),
                }
            return {str(k): self.encode(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.encode(v) for v in value]
        return value

    def append(self, kind, payload):
        with self.lock:
            record = clean(
                {"time": stamp(), "kind": kind, "payload": self.encode(payload)}
            )
            with (self.root / "events.jsonl").open("a") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())


def native_catalog(robot="libero", *, control_mode="native"):
    if robot == "flexiv":
        from robots.flexiv.catalog import catalog

        return catalog(control_mode=control_mode)
    if robot != "libero":
        from rpent.robots.base import _resolve_robot

        return _resolve_robot(robot).native_catalog()

    from robots.libero import tools
    from robots.libero.eef_control import EefControl
    from robots.libero.research import orientation as orientation_module
    from robots.libero.research import placement as placement_module
    from robots.libero.research.orientation import OrientationControl
    from robots.libero.research.placement import PlacementTools
    from robots.libero.research.sensors import ACTIONS
    from rpent.tools import iter_tools
    from rpent.tools.common import CommonTools

    result = []
    for owner in (
        tools,
        tools.LiberoPrimitives,
        CommonTools,
        EefControl,
        PlacementTools,
        OrientationControl,
    ):
        for tool in iter_tools(owner):
            source = inspect.getsource(
                placement_module
                if owner is PlacementTools
                else orientation_module
                if owner is OrientationControl
                else tool.handler
            )
            result.append(
                {
                    "id": "native:" + tool.name,
                    "name": tool.name,
                    "origin": "native",
                    "category": "control"
                    if tool.name in ACTIONS
                    or owner in {EefControl, OrientationControl}
                    or tool.name == "align_placement"
                    else "auxiliary"
                    if owner is CommonTools
                    else "perception",
                    "description": tool.description,
                    "parameters": tool.input_schema,
                    "version": hashlib.sha256(source.encode()).hexdigest(),
                    "source": source,
                    "required": tool.name == "finish",
                    "dependencies": [
                        "align_placement"
                        if tool.name == "preview_placement"
                        else "preview_placement"
                    ]
                    if owner is PlacementTools
                    else [],
                    "validation": "native",
                    "input_contract": "RPent 原生接口；保留原参数、图像与结果反馈",
                    "example": None,
                }
            )
    # Register the API adapter's image reader in the shared toolkit for parity.
    result.append(
        {
            "id": "native:read_image",
            "name": "read_image",
            "origin": "native",
            "category": "perception",
            "description": "Read a saved observation image by artifact name and step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "step": {"type": "integer", "default": -1},
                },
                "required": ["name"],
            },
            "version": "shared-image-reader-v1",
            "required": False,
            "dependencies": [],
            "validation": "native",
            "source": None,
            "example": None,
        }
    )
    return sorted(result, key=lambda x: (x["category"], x["name"]))


class Workbench:
    def __init__(self, config, *, robot="libero"):
        from rpent.dashboard.catalog import load_sources

        self.config = config
        self.robot = robot
        self.planner_view_mode = config.get("planner_view_mode", "native")
        if self.planner_view_mode != "native":
            if robot != "libero":
                raise ValueError("planner_view_mode is available only for LIBERO")
            from robots.libero.research.manual import PLANNER_VIEW_MODE

            if self.planner_view_mode != PLANNER_VIEW_MODE:
                raise ValueError("Unsupported LIBERO planner_view_mode")
        self.initial_action_phase = config.get("initial_action_phase", False)
        if type(self.initial_action_phase) is not bool:
            raise ValueError("initial_action_phase must be a boolean")
        if self.initial_action_phase and robot != "libero":
            raise ValueError("initial_action_phase is available only for LIBERO")
        self.api_recent_image_history = config.get("api_recent_image_history", False)
        if type(self.api_recent_image_history) is not bool:
            raise ValueError("api_recent_image_history must be a boolean")
        if self.api_recent_image_history and robot != "libero":
            raise ValueError("api_recent_image_history is available only for LIBERO")
        self.api_require_finish = config.get("api_require_finish", False)
        if type(self.api_require_finish) is not bool:
            raise ValueError("api_require_finish must be a boolean")
        if self.api_require_finish and robot != "libero":
            raise ValueError(
                "api_require_finish is available only for LIBERO workbenches"
            )
        if config.get("robot", "libero") != robot:
            raise ValueError("Workbench configuration belongs to another robot")
        self.root = Path(config["runs_root"]).resolve()
        history_roots = config.get("history_roots", [])
        if not isinstance(history_roots, list) or any(
            not isinstance(root, str) or not root for root in history_roots
        ):
            raise ValueError("history_roots must be a list of directory paths")
        self.history_roots = [Path(root).resolve() for root in history_roots]
        self.library = Path(config["library_root"]).resolve()
        self.catalog_sources = load_sources(os.environ.get("RPENT_TOOL_CATALOG"))
        self.profiles = {
            p["id"]: {**p, "reasoning_effort": p.get("reasoning_effort") or "none"}
            for p in config["models"]
        }
        self.checks = {}
        self.environment_lock = threading.RLock()
        self.pilot = None
        self.pilot_cell = None
        self.pilot_freeze = None
        self.pilot_defaults = {}

    def bind_pilot(self, root, cell, *, freeze_id=None, run_options=None):
        """Bind server-owned pilot settings; HTTP may change only the cell."""
        if self.robot != "univtac":
            raise ValueError("Pilot cells are available only for UniVTAC")
        from robots.univtac.pilot import Pilot

        pilot = Pilot(root)
        pilot._cell(cell)
        if not (pilot.root / "events.jsonl").is_file():
            raise ValueError("Pilot ledger does not exist")
        self.pilot = pilot
        self.pilot_cell = cell
        self.pilot_freeze = freeze_id
        self.pilot_defaults = dict(run_options or {})

    def pilot_setup(self, selected_cell=None):
        """Read current protocol slots and usage without reserving an episode."""
        if self.pilot is None:
            return None
        from robots.univtac.robot_spec import TASKS

        summary = self.pilot.summary()
        used = {row["id"] for row in summary["rows"]}
        finished = {row["id"] for row in summary["rows"] if "termination_reason" in row}
        active = summary["episodes_reserved"] > summary["finished"]
        freeze_error = None
        try:
            self._pilot_frozen_bundle()
        except (OSError, ValueError) as exc:
            freeze_error = str(exc)
        cells = []
        for cell in self.pilot.manifest["cells"]:
            reason = None
            status = "available"
            if cell["id"] in used:
                status, reason = "used", "This pilot cell has already been used"
            elif cell["model"] == "script":
                status, reason = "script_only", "Script smoke cells are not model runs"
            elif cell["stage"] == "holdout":
                status = "blocked"
                reason = "Held-out experiments are not enabled in this dashboard"
            elif active:
                status, reason = "blocked", "Finish the active pilot episode first"
            elif summary["episodes_reserved"] >= summary["episode_limit"]:
                status, reason = "blocked", "Pilot episode budget exhausted"
            elif cell.get("optional") and summary["frozen"]:
                status, reason = "blocked", "Optional repair is closed after freezing"
            elif cell["stage"] in ("provisional", "validate"):
                required = 4 if cell["stage"] == "provisional" else 6
                if any(
                    previous["id"] not in finished
                    for previous in self.pilot.manifest["cells"][:required]
                ):
                    status = "blocked"
                    reason = f"Finish the first {required} development attempts first"
                elif cell["stage"] == "validate" and freeze_error:
                    status, reason = "blocked", freeze_error
            cells.append(
                {
                    **cell,
                    "task_index": TASKS.index(cell["task"]),
                    "available": reason is None,
                    "status": status,
                    "reason": reason,
                }
            )
        return {
            "selected_cell": selected_cell or self.pilot_cell,
            **{
                key: summary[key]
                for key in (
                    "episodes_reserved",
                    "episode_limit",
                    "finished",
                    "offline_requests",
                    "offline_limit",
                    "schema_version",
                    "development_limit",
                    "holdout_limits",
                )
            },
            "cells": cells,
        }

    def _pilot_frozen_bundle(self):
        frozen = self.pilot._transaction(
            lambda events: (
                next(
                    (event["id"] for event in events if event["kind"] == "frozen"), None
                ),
                None,
            )
        )
        if not self.pilot_freeze or self.pilot_freeze != frozen:
            raise ValueError("Configure the matching frozen bundle before validation")
        return self.pilot.load_freeze(self.pilot_freeze)

    def _available_pilot_cell(self, cell_id):
        if self.pilot is None:
            raise ValueError("This dashboard has no server-configured pilot")
        if not isinstance(cell_id, str) or not cell_id:
            raise ValueError("pilot_cell must be a non-empty protocol cell ID")
        cell = next(
            (cell for cell in self.pilot_setup()["cells"] if cell["id"] == cell_id),
            None,
        )
        if cell is None:
            raise ValueError("Unknown pilot cell")
        if not cell["available"]:
            raise ValueError(cell["reason"])
        return cell

    def validate_pilot_request(self, request):
        """Check the effective claimed configuration before any run starts."""
        if self.pilot is None:
            if "pilot_cell" in request:
                raise ValueError("This dashboard has no server-configured pilot")
            return
        from robots.univtac.pilot.execution import BUDGET, tools_match_for_execution

        cell = self._available_pilot_cell(request.get("pilot_cell"))
        profile = self.profiles[request["model_profile"]]
        if (
            request.get("suite") != "univtac"
            or type(request.get("task")) is not int
            or request["task"] != cell["task_index"]
            or type(request.get("seed")) is not int
            or request["seed"] != cell["seed"]
            or profile["model"].removeprefix("openai-chat:") != cell["model"]
        ):
            raise ValueError("Task, seed and model must match the selected pilot cell")
        if any(
            request.get(key) != BUDGET[key]
            for key in ("max_turns", "planner_timeout_s")
        ):
            raise ValueError(
                "Pilot requires 60 responses and a 3600-second planner budget"
            )
        if cell["stage"] == "provisional":
            generated = [
                tool
                for tool in request["frozen_tools"]
                if tool["origin"] == "generated"
            ]
            if not generated or any(
                tool.get("category") != "perception"
                or tool.get("validation") != "replay_passed"
                for tool in generated
            ):
                raise ValueError("Select replay-validated generated perception tools")
        elif cell["stage"] == "validate":
            expected = self._pilot_frozen_bundle()["conditions"][cell["condition"]][
                "tools"
            ]
            if not tools_match_for_execution(request["frozen_tools"], expected):
                raise ValueError(
                    "Selected tools differ from the frozen validation condition"
                )

    def recover_interrupted(self):
        for path in self.root.glob("*/tasks/*/manifest.json"):
            final = path.parent / "outcome.json"
            if not final.exists():
                write_json(
                    final,
                    {
                        "status": "abnormal_exit",
                        "environment_success": None,
                        "error": "Previous server exited before finalization; inspect flushed events and states.",
                    },
                )
            if (path.parent / "pilot-attempt.json").exists():
                from robots.univtac.pilot.execution import restore_from_output

                restore_from_output(path.parent).after_finish(
                    json.loads(final.read_text())
                )

    @classmethod
    def from_env(cls, *, robot="libero"):
        path = os.environ.get("RPENT_WORKBENCH")
        return cls(json.loads(Path(path).read_text()), robot=robot) if path else None

    def public_profiles(self):
        return [
            {
                k: p.get(k)
                for k in ("id", "label", "planner", "model", "reasoning_effort")
            }
            for p in self.profiles.values()
        ]

    def catalog(self):
        from rpent.dashboard.catalog import combined_catalog, generated_catalog

        result = (
            native_catalog(
                "flexiv", control_mode=self.config.get("control_mode", "native")
            )
            if self.robot == "flexiv"
            else native_catalog(self.robot)
        )
        if self.planner_view_mode != "native":
            from robots.libero.research import manual

            wrapper_source = inspect.getsource(manual)
            for item in result:
                if item["name"] in {"view_env_state", "read_image"}:
                    item["source"] = (item.get("source") or "") + "\n" + wrapper_source
                    item["version"] = hashlib.sha256(
                        item["source"].encode()
                    ).hexdigest()
                    item["description"] = manual.planner_view_description(item["name"])
                    item["input_contract"] = (
                        "Ordered image_views; stored image bytes unchanged"
                    )
        result += generated_catalog(self.library, runs_root=self.root)
        return combined_catalog(result, robot=self.robot, sources=self.catalog_sources)

    def selection(self, ids=None):
        catalog = {t["id"]: t for t in self.catalog()}
        if ids is None:
            ids = [
                i
                for i, t in catalog.items()
                if t["origin"] == "native"
                and t["selectable"]
                and not (
                    self.robot == "libero"
                    and t["name"]
                    in {
                        "move_eef",
                        "translate_to",
                        "rotate_axis",
                        "preview_placement",
                        "align_placement",
                    }
                )
            ]
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
            raise ValueError("tools must be a list of catalog IDs")
        if len(ids) != len(set(ids)) or any(i not in catalog for i in ids):
            raise ValueError("Unknown or duplicate tool/version")
        selected = [catalog[i] for i in ids]
        for item in selected:
            if not item["selectable"]:
                raise ValueError(f"{item['name']}: {item['incompatibility_reason']}")
        names = [t["name"] for t in selected]
        if "finish" not in names or len(names) != len(set(names)):
            raise ValueError("finish is required; select one version per tool name")
        for t in selected:
            missing = set(t.get("dependencies", [])) - set(names)
            if missing:
                raise ValueError(f"{t['name']} requires: {', '.join(sorted(missing))}")
        return selected

    def normalize(self, payload):
        allowed = {
            "model_profile",
            "tools",
            "max_turns",
            "max_tokens",
            "planner_timeout_s",
        }
        if self.pilot is not None:
            allowed.add("pilot_cell")
        if set(payload) - allowed:
            raise ValueError("Use the configured model profile and tool catalog")
        if "model_profile" in payload and payload["model_profile"] not in self.profiles:
            raise ValueError("Unknown model profile")
        if "tools" in payload:
            self.selection(payload["tools"])
        if "pilot_cell" in payload:
            self._available_pilot_cell(payload["pilot_cell"])
        return payload

    def prepare(self, request):
        if "api_recent_image_history" in request:
            raise ValueError("api_recent_image_history is a server-owned setting")
        if "initial_action_phase" in request:
            raise ValueError("initial_action_phase is a server-owned setting")
        if "planner_view_mode" in request:
            raise ValueError("planner_view_mode is a server-owned setting")
        if "api_require_finish" in request:
            raise ValueError("api_require_finish is a server-owned setting")
        if {"pilot_root", "pilot_freeze"} & request.keys():
            raise ValueError("Pilot root and frozen bundle are server-owned settings")
        if self.pilot is not None:
            request = {**self.pilot_defaults, "pilot_cell": self.pilot_cell, **request}
        profile_id = request.get("model_profile", next(iter(self.profiles)))
        if not self.checks.get(profile_id, {}).get("ok"):
            raise ValueError("请先在开始页检查所选模型连接")
        if (
            self.api_recent_image_history
            and self.profiles[profile_id]["planner"] != "api"
        ):
            raise ValueError("api_recent_image_history requires the API planner")
        if self.api_require_finish and self.profiles[profile_id]["planner"] != "api":
            raise ValueError("api_require_finish requires the API planner")
        selected = self.selection(request.get("tools"))
        if self.initial_action_phase:
            if self.profiles[profile_id]["planner"] != "api":
                raise ValueError("initial_action_phase requires the API planner")
            from robots.libero.research.manual import INITIAL_ACTION_PRIMITIVES

            if not ({t["name"] for t in selected} & INITIAL_ACTION_PRIMITIVES):
                raise ValueError(
                    "initial_action_phase requires a selected language primitive"
                )
        prepared = {
            **request,
            "model_profile": profile_id,
            "tools": [t["id"] for t in selected],
            "frozen_tools": selected,
        }
        if self.initial_action_phase:
            prepared["initial_action_phase"] = True
        if self.api_require_finish:
            prepared["api_require_finish"] = True
        if self.api_recent_image_history:
            prepared["api_recent_image_history"] = True
        if self.planner_view_mode != "native":
            prepared["planner_view_mode"] = self.planner_view_mode
        self.validate_pilot_request(prepared)
        if (
            self.pilot
            and self.pilot._cell(prepared["pilot_cell"])["stage"] == "validate"
        ):
            prepared["frozen_tools"] = copy.deepcopy(
                self._pilot_frozen_bundle()["conditions"]["E"]["tools"]
            )
        return prepared

    @contextmanager
    def environment(self, profile_id):
        profile = self.profiles[profile_id]
        self.environment_lock.acquire()
        keys = ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_HOME")
        before = {k: os.environ.get(k) for k in keys}
        try:
            for k in keys:
                os.environ.pop(k, None)
            if profile.get("key_file"):
                os.environ["OPENAI_API_KEY"] = (
                    Path(profile["key_file"]).read_text().strip()
                )
            if profile.get("codex_home"):
                os.environ["CODEX_HOME"] = profile["codex_home"]
            yield profile
        finally:
            for k, v in before.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            self.environment_lock.release()

    def check(self, profile_id):
        from rpent.planner.check import LlmCheckRequest, check_llm

        if profile_id not in self.profiles:
            raise ValueError("Unknown model profile")
        request_id = (
            self.pilot.reserve_offline("connectivity", None, []) if self.pilot else None
        )
        try:
            with self.environment(profile_id) as p:
                result = check_llm(
                    LlmCheckRequest(
                        planner=p["planner"],
                        model=p["model"],
                        base_url=p.get("base_url"),
                        timeout_s=60,
                    )
                ).as_dict()
        except BaseException as exc:
            if request_id is not None:
                failure = clean(
                    {
                        "ok": False,
                        "status": "error",
                        "detail": f"{type(exc).__name__}: {exc}",
                        "checked_at": stamp(),
                    }
                )
                self.checks[profile_id] = failure
                self.pilot.finish_offline(
                    request_id, {"model_profile": profile_id, **failure}
                )
            raise
        result["checked_at"] = stamp()
        self.checks[profile_id] = clean(result)
        if request_id is not None:
            self.pilot.finish_offline(
                request_id, {"model_profile": profile_id, **self.checks[profile_id]}
            )
        return self.checks[profile_id]

    def runs(self):
        result = []
        seen = set()
        paths = (
            (source, path)
            for source in [self.root, *self.history_roots]
            for path in source.glob("*/tasks/*/dashboard_config.json")
        )
        for source, path in paths:
            root = path.parent.resolve()
            if root in seen or not root.is_relative_to(source):
                continue
            seen.add(root)
            try:
                config = json.loads(path.read_text())
                if config.get("robot", self.robot) != self.robot:
                    continue
                manifest = root / "manifest.json"
                data = json.loads(manifest.read_text()) if manifest.exists() else {}
                final = root / "outcome.json"
                outcome = json.loads(final.read_text()) if final.exists() else {}
                identity = (
                    str(path.parent.relative_to(self.root))
                    if source == self.root
                    else f"history:{root}"
                )
                result.append(
                    {
                        "id": hashlib.sha256(identity.encode()).hexdigest()[:20],
                        "instruction": self._run_instruction(root),
                        "path": str(root),
                        "config": config,
                        "manifest": data,
                        "outcome": outcome,
                        "updated": path.stat().st_mtime,
                    }
                )
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda x: x["updated"], reverse=True)

    @staticmethod
    def _run_instruction(root):
        try:
            states = json.loads((root / "states.json").read_text())
            for step in states.get("steps", []):
                instruction = step.get("extras", {}).get("task_language")
                if isinstance(instruction, str) and instruction.strip():
                    return instruction
        except (OSError, ValueError):
            pass
        return None

    def run(self, run_id):
        for item in self.runs():
            if item["id"] == run_id:
                root = Path(item["path"])
                item["files"] = sorted(
                    str(p.relative_to(root))
                    for p in root.rglob("*")
                    if p.is_file()
                    and (
                        not p.is_symlink()
                        or (
                            p == root / "episode.mp4"
                            and p.resolve().is_relative_to(root.resolve())
                        )
                    )
                )
                return item
        raise ValueError("Unknown run")

    def artifact(self, run_id, name):
        root = Path(self.run(run_id)["path"]).resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Unknown artifact")
        return path


def publish(library_root, tool, metadata):
    """Called explicitly by Codex; publication never selects a tool for a run."""
    from robots.libero.research.library import Library

    library = Library(Path(library_root))
    version = library.save([tool])
    path = Path(library_root) / f"{version}.meta.json"
    if not path.exists() and metadata.get("previous_version"):
        (previous,) = library.load(metadata["previous_version"])
        metadata = {
            **metadata,
            "diff": "".join(
                difflib.unified_diff(
                    previous["source"].splitlines(True),
                    tool["source"].splitlines(True),
                    fromfile=metadata["previous_version"],
                    tofile=version,
                )
            ),
        }
    if not path.exists():
        write_json(
            path,
            {
                "created_at": stamp(),
                "dependencies": [],
                "validation": "unverified",
                "input_contract": "Up to 4 recorded frames; calibrated 256x256 RGB/depth/world in metres; proprioception and SAM3 masks.",
                **metadata,
            },
        )
    # Published tools expose only the latest version of each name. Runs own
    # their frozen source, so removing library entries cannot rewrite history.
    for old_meta in list(library.root.glob("*.meta.json")):
        old_version = old_meta.name.removesuffix(".meta.json")
        if old_version != version:
            (old_tool,) = library.load(old_version)
            if old_tool["name"] == tool["name"]:
                old_meta.unlink()
                (library.root / f"{old_version}.json").unlink()
    return version


def source_snapshot(root, output):
    """Record code, including untracked integration modules but not run data."""
    root, output = Path(root), Path(output)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "HEAD", "--", "rpent", "robots", "tests"],
        cwd=root,
        capture_output=True,
        text=True,
    ).stdout
    (output / "code.diff").write_text(clean(diff))
    files = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "rpent",
            "robots",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    hashes = {}
    for name in files:
        path = root / name
        if (
            path.name.startswith("._")
            or path.suffix not in {".py", ".html", ".js", ".css"}
            or not path.is_file()
        ):
            continue
        data = clean(path.read_text())
        target = output / "code" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)
        hashes[name] = hashlib.sha256(data.encode()).hexdigest()
    return {"revision": revision, "files": hashes}


def termination_reason(error, aborted, finish, solved):
    if aborted:
        return "aborted"
    message = (error or "").lower()
    if any(
        term in message
        for term in (
            "connection",
            "network",
            "connecterror",
            "dns",
            "stream disconnected",
        )
    ):
        return "network_failure"
    if "timed out" in message or "timeout" in message:
        return "timeout"
    if "unsupported reasoning" in message or "configuration" in message:
        return "configuration_error"
    if error:
        return "error"
    if finish or solved:
        return "completed"
    return "budget_exhausted"
