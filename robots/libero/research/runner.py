# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Bounded teacher → library → actor evaluation loop for LIBERO."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from robots.libero.research.library import Library, Sandbox, digest
from robots.libero.research.models import TEACHER_PROMPT, Model
from robots.libero.research.native import SYSTEM_PROMPT
from rpent.utils.logging import get_logger, init_output_dir

logger = get_logger("sensor_research")


def save(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False))
    temporary.replace(path)


def verify_splits(config: dict, suite) -> list[dict]:
    """Verify actual initial-state identity, rather than nominal random seeds."""
    import numpy as np

    manifest = []
    for task in config["tasks"]:
        initial = suite.get_task_init_states(task)
        identities = {}
        for split, seeds in config["splits"].items():
            if not seeds:
                raise ValueError(f"empty split: {split}")
            for seed in seeds:
                if seed < 0:
                    raise ValueError("seed must be nonnegative")
                index = seed % len(initial)
                fingerprint = hashlib.sha256(
                    np.asarray(initial[index]).tobytes()
                ).hexdigest()
                if fingerprint in identities:
                    raise ValueError(
                        f"repeated initial state for task {task}: {identities[fingerprint]} and {split}/{seed}"
                    )
                identities[fingerprint] = (split, seed)
                manifest.append(
                    {
                        "task": task,
                        "split": split,
                        "seed": seed,
                        "initial_state_index": index,
                        "initial_state_sha256": fingerprint,
                        "instruction": suite.get_task(task).language,
                    }
                )
    return manifest


def accept_candidate(previous: list[dict], candidate: list[dict]) -> bool:
    """Development gate: paired wins increase and no task's total regresses."""

    def indexed(rows):
        return {(r["task"], r["seed"]): r for r in rows}

    old, new = indexed(previous), indexed(candidate)
    if (
        not old
        or old.keys() != new.keys()
        or len(old) != len(previous)
        or len(new) != len(candidate)
    ):
        raise ValueError("evaluation cells do not match")
    if any(r.get("error") for r in previous + candidate) or any(
        r.get("sensor_tool_errors", 0) for r in candidate
    ):
        return False
    tasks = {task for task, _ in old}

    def totals(rows, task):
        return sum(
            bool(row["native_success"]) for (t, _), row in rows.items() if t == task
        )

    return all(totals(new, t) >= totals(old, t) for t in tasks) and sum(
        r["native_success"] for r in new.values()
    ) > sum(r["native_success"] for r in old.values())


def episode(
    config: dict,
    cell: dict,
    tools: list[dict],
    model: Model,
    sandbox: Sandbox,
    root: Path,
) -> dict:
    """Dispatch one episode to the native RPent CLI; never own an action loop."""
    root.mkdir(parents=True, exist_ok=False)
    root = root.resolve()
    library_path = root / "frozen-library.json"
    save(library_path, tools)
    backend = model.config
    planner = "codex" if backend["kind"] == "codex_sdk" else "api"
    if backend["kind"] not in {"codex_sdk", "chat_completions"}:
        raise ValueError("native episodes require codex_sdk or chat_completions")
    model_name = (
        backend["model"] if planner == "codex" else "openai-chat:" + backend["model"]
    )
    command = [
        sys.executable,
        "-m",
        "rpent.cli.main",
        "--robot",
        "libero",
        "--planner",
        planner,
        "--model",
        model_name,
        "--suite",
        config["suite"],
        "--task",
        str(cell["task"]),
        "--seed",
        str(cell["seed"]),
        "--libero-type",
        config["libero_type"],
        "--max-turns",
        str(config["max_turns"]),
        "--max-episode-steps",
        str(config["max_episode_steps"]),
        "--max-tokens",
        str(backend.get("max_tokens", 4096)),
        "--sensor-library",
        str(library_path),
        "--memory-profile",
        "local",
        "--sensor-sandbox-image",
        sandbox.image,
        "--output-dir",
        str(root / "native"),
    ]
    for name in ("vla_endpoint", "sam3_endpoint"):
        if config.get(name):
            command += ["--" + name.replace("_", "-"), config[name]]
    env = os.environ.copy()
    if planner == "api":
        command += ["--base-url", backend["url"]]
        env["OPENAI_API_KEY"] = (
            os.environ[backend["key_env"]] if backend.get("key_env") else "local"
        )
    started = time.monotonic()
    report = {
        **cell,
        "library": digest(tools),
        "model": backend["model"],
        "native_success": False,
        "trajectory": [],
        "requests": [],
    }
    with (root / "native-cli.log").open("w") as log:
        process = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    result_path = root / "native" / "research-report.json"
    if result_path.exists():
        report.update(json.loads(result_path.read_text()))
        report["model"] = backend["model"]
    if process.returncode:
        report["error"] = (
            report.get("error")
            or f"native RPent exited {process.returncode}; see native-cli.log"
        )
    elif not result_path.exists():
        report["error"] = "native RPent did not write an evaluator report"
    trajectory = report["trajectory"]
    generated = [
        t
        for t in trajectory
        if t.get("decision", {}).get("tool", "").startswith("sensor_")
    ]
    report["sensor_tool_calls"] = len(generated)
    report["sensor_tool_errors"] = sum(
        bool(t["result"].get("error")) for t in generated
    )
    report["seconds"] = round(time.monotonic() - started, 3)
    # Export only RGB evidence for offline teacher feedback, never private states.
    for index, camera in enumerate(("agentview", "wrist")):
        frames = sorted(
            (root / "native" / f"{camera}.png").glob("*.png"), key=lambda p: int(p.stem)
        )
        if frames:
            shutil.copyfile(frames[0], root / f"initial-{index}.png")
            shutil.copyfile(frames[-1], root / f"last-{index}.png")
    save(root / "report.json", report)
    return report


def reuse_baseline(
    source: Path,
    destination: Path,
    protocol: dict,
    cells: list[dict],
    version: str,
    config: dict,
) -> tuple[list[dict], list[dict]]:
    """Reuse a paused baseline only when the comparison protocol still matches."""
    source = source.resolve()
    pause = json.loads((source / "pause.json").read_text())
    if pause.get("phase") != "baseline_complete":
        raise ValueError("source is not a completed baseline checkpoint")
    if json.loads((source / "protocol.json").read_text()) != protocol:
        raise ValueError("checkpoint protocol changed; collect a new baseline")
    if json.loads((source / "splits.json").read_text()) != cells:
        raise ValueError("checkpoint initial states changed")
    inherited = []
    hashes = {}
    for label, split, role in (
        ("teacher-explore", "explore", "teacher"),
        ("baseline", "validation", "actor"),
    ):
        path = source / f"{label}.json"
        rows = json.loads(path.read_text())
        expected = {(c["task"], c["seed"]): c for c in cells if c["split"] == split}
        actual = {(r["task"], r["seed"]): r for r in rows}
        if actual.keys() != expected.keys() or len(actual) != len(rows):
            raise ValueError("checkpoint episode set does not match")
        for key, row in actual.items():
            if (
                row.get("error")
                or row["library"] != version
                or row["model"] != config[role]["model"]
                or row["initial_state_sha256"] != expected[key]["initial_state_sha256"]
            ):
                raise ValueError("checkpoint episode is invalid or incompatible")
        inherited.append(rows)
        hashes[label] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Only copy the explicit development reports and sensor PNGs, not private state.
    for label, rows in zip(("teacher-explore", "baseline"), inherited, strict=True):
        save(destination / f"{label}.json", rows)
        for row in rows:
            cell = f"t{row['task']}-s{row['seed']}"
            target = destination / label / cell
            target.mkdir(parents=True)
            for name in ("initial-0.png", "initial-1.png", "last-0.png", "last-1.png"):
                image = source / label / cell / name
                if image.is_file():
                    shutil.copyfile(image, target / name)
    save(
        destination / "baseline-provenance.json",
        {"source": str(source), "report_sha256": hashes},
    )
    return tuple(inherited)


def run(
    config: dict,
    root: Path,
    *,
    heldout: bool = False,
    stop_after_baseline: bool = False,
    baseline_from: Path | None = None,
) -> None:
    os.environ["LIBERO_TYPE"] = config["libero_type"]
    if heldout and not config.get("start_version"):
        raise ValueError("heldout evaluation requires an explicit frozen start_version")
    from rlinf.envs.sim.libero.utils import benchmark

    suite = benchmark.get_benchmark(config["suite"])()
    cells = verify_splits(config, suite)
    sandbox = Sandbox(config["sandbox_image"])
    root.mkdir(parents=True, exist_ok=False)
    init_output_dir(root)
    save(root / "config.json", config)
    save(root / "splits.json", cells)
    save(
        root / "protocol.json",
        {
            "config_sha256": digest(config),
            "episode_backend": "native-rpent-v1",
            "native_execution_sha256": digest(
                {
                    name: hashlib.sha256(
                        Path(__file__).parents[3].joinpath(name).read_bytes()
                    ).hexdigest()
                    for name in (
                        "robots/libero/research/native.py",
                        "robots/libero/research/sensors.py",
                        "robots/libero/robot_spec.py",
                        "robots/libero/prompt_bundle.py",
                        "robots/libero/memory.py",
                        "rpent/tools/toolkit.py",
                        "rpent/planner/api_loop.py",
                        "rpent/planner/codex.py",
                    )
                }
            ),
            "actor_prompt_sha256": digest(SYSTEM_PROMPT),
            "teacher_prompt_sha256": digest(TEACHER_PROMPT),
            "sandbox_image": sandbox.image,
            "controller_sha256": hashlib.sha256(
                Path(__file__).parents[1].joinpath("tools.py").read_bytes()
            ).hexdigest(),
        },
    )
    library = Library(Path(config["library_dir"]))
    empty = library.save([])
    current = config.get("start_version", empty)
    actor = Model(config["actor"])
    teacher = Model(config["teacher"])

    def batch(split: str, version: str, model: Model, label: str) -> list[dict]:
        results = []
        frozen = library.load(version)
        for cell in cells:
            if cell["split"] == split:
                directory = root / label / f"t{cell['task']}-s{cell['seed']}"
                results.append(episode(config, cell, frozen, model, sandbox, directory))
                save(root / f"{label}.json", results)
        return results

    if heldout:
        # Explicit frozen evaluation; no teacher calls or promotion in this path.
        baseline = batch("heldout", empty, actor, "heldout-basic")
        final = batch("heldout", current, actor, "heldout-library")
        save(
            root / "summary.json",
            {"version": current, "baseline": baseline, "final": final, "heldout": True},
        )
        return
    if baseline_from is None:
        exploration = batch("explore", current, teacher, "teacher-explore")
        incumbent = batch("validation", current, actor, "baseline")
    else:
        exploration, incumbent = reuse_baseline(
            baseline_from,
            root,
            json.loads((root / "protocol.json").read_text()),
            cells,
            current,
            config,
        )
    if any(row.get("error") for row in exploration + incumbent):
        raise RuntimeError(
            "development runtime failed; inspect episode reports before tuning tools"
        )
    if stop_after_baseline:
        save(
            root / "pause.json",
            {"phase": "baseline_complete", "next": "teacher_tool_proposal"},
        )
        return
    rounds = []
    feedback = None
    for iteration in range(config["iterations"]):
        folder = root / f"round-{iteration}"
        folder.mkdir()
        payload = {
            "library": library.load(current),
            "exploration": exploration,
            "incumbent_validation": incumbent,
            "previous_candidate_feedback": feedback,
        }
        # Label development images so teacher feedback refers to the right episode.
        images, image_context = [], []
        labels = ["teacher-explore", "baseline"]
        if iteration:
            labels.append(f"candidate-{iteration - 1}")
        for label in labels:
            for cell_dir in sorted((root / label).glob("t*-s*")):
                for name in ("initial-0.png", "last-0.png", "last-1.png"):
                    path = cell_dir / name
                    if path.exists():
                        image_context.append(
                            {
                                "index": len(images),
                                "episode": f"{label}/{cell_dir.name}",
                                "frame": "initial"
                                if name.startswith("initial")
                                else "last",
                                "camera": "agentview"
                                if name.endswith("0.png")
                                else "wrist",
                            }
                        )
                        images.append(path.read_bytes())
        payload["image_context"] = image_context
        try:
            proposal, usage = teacher.complete(TEACHER_PROMPT, payload, images)
            save(folder / "proposal.json", {"proposal": proposal, "request": usage})
            if not proposal.get("hypothesis"):
                raise ValueError("proposal needs a failure hypothesis")
            candidate = library.save(proposal["tools"])
            result = batch("validation", candidate, actor, f"candidate-{iteration}")
            accepted = accept_candidate(incumbent, result)
            feedback = {
                "version": candidate,
                "hypothesis": proposal["hypothesis"],
                "tools": proposal["tools"],
                "accepted": accepted,
                "validation": result,
            }
            if accepted:
                current, incumbent = candidate, result
                library.promote(current)
        except Exception as exc:
            feedback = {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}
            logger.exception("candidate round failed")
        rounds.append(feedback)
        save(folder / "decision.json", feedback)
        save(
            root / "summary.json",
            {"version": current, "rounds": rounds, "heldout": False},
        )
    library.promote(current)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--heldout", action="store_true")
    mode.add_argument("--stop-after-baseline", action="store_true")
    mode.add_argument("--baseline-from", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if "action_chunks" in config:
        raise ValueError(
            "remove action_chunks; research uses unchanged RPent controller defaults"
        )
    if set(config["splits"]) != {"explore", "validation", "heldout"}:
        raise ValueError("define explore, validation and heldout splits")
    if len(set(config["tasks"])) != len(config["tasks"]):
        raise ValueError("duplicate tasks")
    if config["iterations"] < 1 or config["max_turns"] < 1:
        raise ValueError("budgets must be positive")
    run(
        config,
        args.output.resolve(),
        heldout=args.heldout,
        stop_after_baseline=args.stop_after_baseline,
        baseline_from=args.baseline_from,
    )


if __name__ == "__main__":
    main()
