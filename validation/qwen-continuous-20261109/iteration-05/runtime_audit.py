# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Read-only process snapshots scoped to this experiment's systemd unit."""

import hashlib
import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

PROXIES = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


class RuntimeAudit:
    def __init__(self, root, lane, settings, source):
        self.root, self.lane = Path(root), lane
        self.settings, self.source = settings, str(source)
        self.stop_requested = threading.Event()
        self.thread = None
        self.seen = set()
        self.report = {
            "lane": lane,
            "audit_type": "contemporaneous_owned_process_observer",
            "snapshots": [],
            "observer_errors": [],
            "observer_stopped": False,
        }
        group = subprocess.check_output(
            [
                "systemctl",
                "--user",
                "show",
                settings["unit"],
                "-p",
                "ControlGroup",
                "--value",
            ],
            text=True,
        ).strip()
        command = subprocess.check_output(
            [
                "systemctl",
                "--user",
                "show",
                settings["unit"],
                "-p",
                "ExecStart",
                "--value",
            ],
            text=True,
        )
        assert str(self.root / lane / "start.sh") in command, (
            "Observer unit ownership mismatch"
        )
        assert group.startswith("/user.slice/"), "Unexpected unit cgroup"
        self.cgroup = Path("/sys/fs/cgroup" + group)

    def save(self):
        path = self.root / self.lane / "runtime-audit.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.report, indent=2) + "\n")
        temporary.replace(path)

    def sample(self):
        pids = set()
        for file in self.cgroup.rglob("cgroup.procs"):
            try:
                pids.update(int(value) for value in file.read_text().split())
            except FileNotFoundError:
                continue
        for pid in sorted(pids):
            proc = Path("/proc") / str(pid)
            try:
                raw_command = (proc / "cmdline").read_bytes()
                args = [v.decode() for v in raw_command.split(b"\0") if v]
                start_ticks = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]
                identity = (pid, start_ticks)
                if identity in self.seen:
                    continue
                entrypoint = (
                    args[1]
                    if len(args) > 1
                    and args[1].endswith("/robots/libero/env_server.py")
                    else None
                )
                role = (
                    "environment_server"
                    if entrypoint
                    else "workbench"
                    if args[1:3] == ["-m", "rpent.cli.main"]
                    else None
                )
                if role is None:
                    continue
                env = dict(
                    v.split(b"=", 1)
                    for v in (proc / "environ").read_bytes().split(b"\0")
                    if b"=" in v
                )
            except (FileNotFoundError, ProcessLookupError):
                continue
            paths = {
                key: env.get(key.encode(), b"").decode()
                for key in ["RPENT_REPO_ROOT", "PYTHONPATH", "LIBERO_CONFIG_PATH"]
            }
            snapshot = {
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "pid": pid,
                "start_ticks": start_ticks,
                "role": role,
                "entrypoint": entrypoint or "rpent.cli.main",
                "command_sha256": hashlib.sha256(raw_command).hexdigest(),
                "eef_control_flag_present": "--enable-eef-control" in args,
                "source_environment": paths,
                "source_roots_match": paths["RPENT_REPO_ROOT"] == self.source
                and self.source in paths["PYTHONPATH"].split(":"),
                "private_config_matches": paths["LIBERO_CONFIG_PATH"]
                == str(self.root / self.lane / "libero-config"),
                "proxy_variables_present": [
                    key for key in PROXIES if key.encode() in env
                ],
            }
            if role == "environment_server":
                snapshot["entrypoint_matches"] = entrypoint == str(
                    Path(self.source) / "robots/libero/env_server.py"
                )
            self.seen.add(identity)
            self.report["snapshots"].append(snapshot)
            self.save()

    def observe(self):
        try:
            while not self.stop_requested.is_set():
                self.sample()
                self.stop_requested.wait(0.2)
        except Exception as exc:
            self.report["observer_errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            self.report["observer_stopped"] = True
            self.save()

    def start(self):
        self.save()
        self.thread = threading.Thread(target=self.observe, daemon=True)
        self.thread.start()

    def stop(self, outcome=None):
        self.stop_requested.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError(
                    "Owned process observer did not stop within two seconds"
                )
        ended_at = (outcome or {}).get("ended_at")
        snapshots = self.report["snapshots"]
        children = [s for s in snapshots if s["role"] == "environment_server"]
        self.report["episode_ended_at"] = ended_at
        self.report["child_observed_before_episode_end"] = bool(ended_at) and any(
            datetime.fromisoformat(s["observed_at"]) <= datetime.fromisoformat(ended_at)
            for s in children
        )
        self.report["coverage_complete"] = (
            self.report["child_observed_before_episode_end"]
            and any(s["role"] == "workbench" for s in snapshots)
            and not self.report["observer_errors"]
        )
        self.report["guard_violations"] = [
            {"pid": s["pid"], "role": s["role"]}
            for s in snapshots
            if not s["source_roots_match"]
            or not s["private_config_matches"]
            or s["proxy_variables_present"]
            or s["eef_control_flag_present"]
            or (s["role"] == "environment_server" and not s["entrypoint_matches"])
        ]
        self.save()
        return self.report
