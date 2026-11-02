# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Task-0-only tool development, followed by a frozen ten-episode evaluation."""

import argparse
import copy
import csv
import hashlib
import json
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from examples.univtac.raw_depth_baseline import TOOLS, summarize
from robots.libero.research import codex_sdk
from robots.libero.research.library import Sandbox, digest, validate_tools
from robots.univtac.instructions import SEEN_INSTRUCTIONS
from robots.univtac.pilot.evidence import export_development
from robots.univtac.pilot.maker import summarize_inputs
from robots.univtac.pilot.replay import load_frames
from rpent.dashboard.workbench import RunJournal, clean, publish, write_json

NATIVE = ["native:" + name for name in sorted(TOOLS)]
NAME = "sensor_modal_evidence"
MAKER_INPUT_CHARS = 320000
TOOL_RESULT_CHARS = 1500
FIELDS = (
    "prompt_bundle.py",
    "toolkit.py",
    "control.py",
    "backend.py",
    "observations.py",
    "instructions.py",
)
MAKER = """Develop ONE reusable perception program from these task-0 robot interactions.
Return a JSON declaration defining run(frames, params) -> a compact finite JSON dict.
Use the name sensor_modal_evidence for every revision. NumPy and standard library only.
It receives the most recent 1..4 complete sensor frames, oldest first. Combine modalities
or temporal evidence when justified by these interactions. Reduce repeated reasoning and
unproductive probing; do not just wrap a native query. State useful measurements, uncertainty,
evidence frame numbers and applicability. Do not output motions, task recipes, object names,
fixed target coordinates, hidden geometry, or official success predictions. Do not encode
task IDs. No files, network, GPU, model calls or motion control. Missing evidence is unknown.
The source data are head/wrist RGB and camera depth in metres with calibration;
tactile.left/right RGB, initial reference (possibly already loaded), native camera depth
in millimetres (not indentation), and marker reference/current/displacement in pixels;
state.eef_pose_wxyz is a measured world-frame hand pose [x,y,z,qw,qx,qy,qz].
Marker rows can be shuffled/resampled: do not assume row identity across frames.
Tools receive full arrays, although maker depth inputs are explicitly sampled summaries.
Read image/coordinate metadata. Do not interpret pixel displacement as calibrated force.
Write a concise, easy-to-use description explaining when to call, parameters, output and
limitations. Provide valid replay_params_json. Prefer few parameters with defaults. Handle
one-frame and missing-sensor cases honestly. Keep tool results below 1500 JSON characters
and the description below 700 characters. Focus on ONE repeated inference evident in the
records, with a small set of decisive outputs. Do not produce a catalogue of sensor statistics.
The previous broad statistics tools were frequently called without reducing policy reasoning.
Compute a useful relationship or supported diagnosis rather than delegating all interpretation
back to the policy. Distinguish measured evidence from hypotheses and unknowns. Describe when
the result can replace redundant raw queries; do not demand a call on every observation.
Do not remove native observations or alter the control interface to manufacture token savings.
Maker-only sampling/rounding and omitted feedback are explicitly labelled; runtime arrays
remain complete. No sample statistics are claimed to represent every marker or pixel.
Use only supplied DEVELOPMENT records. This is program generation, not a replayed policy trial.
When a previous candidate is supplied, revise it using the observed failures. Explain one
testable change in reason; distinguish program changes from documentation changes. Keep the
response under 10000 output tokens (soft, checked afterward).
"""
MAKER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "name",
        "description",
        "parameters_json",
        "source",
        "replay_params_json",
        "reason",
    ],
    "properties": {
        k: {"type": "string"}
        for k in (
            "name",
            "description",
            "parameters_json",
            "source",
            "replay_params_json",
            "reason",
        )
    },
}
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["token_benefit", "success_benefit", "stop_recommended", "reason"],
    "properties": {
        **{
            k: {"type": "boolean"}
            for k in ("token_benefit", "success_benefit", "stop_recommended")
        },
        "reason": {"type": "string"},
    },
}


def score(rows):
    """Rank official successes first, then mean total provider tokens."""
    values = [
        r["input_tokens"] + r["output_tokens"]
        for r in rows
        if r.get("input_tokens") is not None and r.get("output_tokens") is not None
    ]
    return {
        "successes": sum(r["official_success"] is True for r in rows),
        "trials": len(rows),
        "token_records": len(values),
        "mean_total_tokens": sum(values) / len(values)
        if len(values) == len(rows)
        else None,
        "mean_elapsed_s": sum(r["elapsed_s"] for r in rows) / len(rows),
        "mean_uncached_input_tokens": sum(
            r["input_tokens"] - r["cached_input_tokens"] for r in rows
        )
        / len(rows)
        if all(
            r.get("input_tokens") is not None
            and r.get("cached_input_tokens") is not None
            for r in rows
        )
        else None,
    }


def better(candidate, best):
    if candidate["successes"] != best["successes"]:
        return candidate["successes"] > best["successes"]
    return (
        candidate["mean_total_tokens"] is not None
        and best["mean_total_tokens"] is not None
        and candidate["mean_total_tokens"] < best["mean_total_tokens"]
    )


def valid_tool_calls(rows):
    """Count successful executions, preserving errors separately from adoption."""
    valid, failed = 0, 0
    for row in rows:
        for line in (Path(row["path"]) / "events.jsonl").read_text().splitlines():
            event = json.loads(line)
            payload = event["payload"]
            if event["kind"] == "tool_response" and payload.get("name") == NAME:
                result = payload.get("result", {})
                if result.get("error") is not None or result.get("errors"):
                    failed += 1
                else:
                    valid += 1
    return {"valid_calls": valid, "error_calls": failed}


def early_stop(candidate, baseline, judgement):
    return (
        candidate["successes"] == candidate["trials"] == 3
        and candidate["mean_total_tokens"] is not None
        and baseline["mean_total_tokens"] is not None
        and candidate["mean_total_tokens"] <= baseline["mean_total_tokens"] * 0.8
        and judgement["token_benefit"]
        and judgement["stop_recommended"]
    )


class MakerInputBudgetError(ValueError):
    """Input construction must be fixed before spending another maker attempt."""


def compact_maker_input(payload):
    """Bound maker evidence without changing sensor archives or policy inputs."""
    compact = copy.deepcopy(payload)

    def indices(length, count):
        if length <= count:
            return list(range(length))
        return sorted({round(i * (length - 1) / (count - 1)) for i in range(count)})

    for run in compact.get("development", []):
        for frame in run.get("frames", []):
            for sensor in frame.get("tactile", {}).values():
                arrays = [
                    sensor[name]
                    for name in (
                        "marker_reference",
                        "marker_current",
                        "marker_displacement",
                    )
                    if isinstance(sensor.get(name), dict)
                    and isinstance(sensor[name].get("values"), list)
                ]
                # Shared indices preserve each sampled reference/current pairing.
                for array in arrays:
                    values = array["values"]
                    selected = indices(len(values), 32)
                    array["original_shape"] = array.get("shape")
                    array["sample_indices"] = selected
                    array["values"] = [values[i] for i in selected]
                    if array.get("shape"):
                        array["shape"] = [len(selected), *array["shape"][1:]]
        # Preserve every measured pose and issued command without repeating the
        # same chunk receipt at every intermediate physics frame.
        for action in run.get("actions", {}).get("steps", []):
            state = action.get("state", {})
            action["state"] = {
                key: state[key] for key in ("eef_pose_wxyz", "gripper") if key in state
            }
            receipt = action.pop("receipt", {})
            if "command" in action:
                action["receipt"] = {
                    key: receipt[key]
                    for key in (
                        "exec_success",
                        "reason",
                        "error",
                        "executed_commands",
                        "position_error_m",
                        "orientation_error_rad",
                    )
                    if key in receipt
                }

    for run in compact.get("user_feedback", []):
        feedback = run.get("feedback", {})
        calls = feedback.get("calls", [])
        chosen = set()
        for name in sorted({c["name"] for c in calls}):
            group = [i for i, c in enumerate(calls) if c["name"] == name]
            chosen.update(group[i] for i in indices(len(group), 3))
            errors = [
                i
                for i in group
                if calls[i].get("result", {}).get("error")
                or calls[i].get("result", {}).get("errors")
            ]
            chosen.update(errors[i] for i in indices(len(errors), 3))
        feedback["call_counts"] = dict(Counter(c["name"] for c in calls))
        feedback["call_sequence"] = [
            {"index": i, "name": c["name"], "step": c.get("result", {}).get("step")}
            for i, c in enumerate(calls)
        ]
        feedback["selected_call_indices"] = sorted(chosen)
        feedback["omitted_call_details"] = len(calls) - len(chosen)
        feedback["calls"] = [calls[i] for i in sorted(chosen)]

    if compact.get("previous_candidate"):
        compact.pop("base_source", None)

    def rounded(value):
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, dict):
            return {k: rounded(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rounded(v) for v in value]
        return value

    compact = rounded(compact)
    compact["maker_sampling"] = {
        "numeric_decimals": 6,
        "marker_rows_per_frame": 32,
        "feedback": "up to three evenly spaced calls and three errors per tool/run; complete call order and measured pose/command trace retained, chunk receipts only on command frames",
        "scope": "Maker text only; archived images and runtime tool arrays unchanged",
    }
    return compact


def input_budget_failure(exc):
    return isinstance(exc, MakerInputBudgetError) or (
        "Input exceeds the maximum length" in str(exc)
    )


def log_iteration(root, iteration, evaluation, baseline):
    """Append research evidence; plot the primary success metric."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from style_presets import rcparams

    measured = evaluation.get("score")
    metric = measured["successes"] / measured["trials"] if measured else None
    delta = metric - baseline["successes"] / 3 if metric is not None else None
    status = (
        "baseline"
        if iteration == 0
        else "kept"
        if evaluation.get("kept")
        else "reverted"
    )
    now = datetime.now(timezone.utc).isoformat()
    text = json.dumps(evaluation, ensure_ascii=False)
    with (root / "research_log.md").open("a") as stream:
        stream.write(f"\n## Iteration {iteration} — {now}\n\n{text}\n")
    with (root / "research.md").open("a") as stream:
        stream.write(f"\n| {iteration} | {status} | {metric} | {text} |\n")
    path = root / "autoresearch-results.tsv"
    fresh = not path.exists()
    with path.open("a") as stream:
        writer = csv.writer(stream, delimiter="\t")
        if fresh:
            writer.writerow(
                [
                    "iteration",
                    "metric_value",
                    "delta",
                    "delta_pct",
                    "status",
                    "description",
                    "evaluator_source",
                    "timestamp",
                ]
            )
        writer.writerow(
            [iteration, metric, delta, "-", status, text, "mechanical", now]
        )
    rows = [
        row
        for row in csv.DictReader(path.open(), delimiter="\t")
        if row["metric_value"]
    ]
    rcparams()
    figure, axis = plt.subplots(figsize=(7, 4))
    axis.plot(
        [int(r["iteration"]) for r in rows],
        [float(r["metric_value"]) for r in rows],
        "o-",
    )
    axis.axhline(1, linestyle="--", color="gray")
    axis.set(
        xlabel="Optimization", ylabel="Development success rate", ylim=(-0.05, 1.05)
    )
    figure.tight_layout()
    figure.savefig(root / "progress.png", dpi=150)
    plt.close(figure)


class Experiment:
    def __init__(self, url, root):
        self.url, self.root = url, root
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        state = self.api("/api/session/state")
        if state["session_state"] != "ready":
            raise RuntimeError("Dashboard must be idle before attaching the experiment")
        self.server_id = state["server_id"]
        self.hashes = {
            name: hashlib.sha256(
                (Path("robots/univtac") / name).read_bytes()
            ).hexdigest()
            for name in FIELDS
        }
        self.base_config = self.api("/api/session/config")
        if (
            self.base_config.get("model") != "gpt-6-astra"
            or self.base_config.get("reasoning_effort") != "high"
        ):
            raise ValueError("Astra high is required")

    def api(self, path, payload=None):
        request = urllib.request.Request(
            self.url + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with self.opener.open(request, timeout=20) as response:
            return json.load(response)

    def status(self, **data):
        write_json(self.root / "status.json", data)

    def group(self, label, trials, tools):
        output = self.root / label
        output.mkdir(exist_ok=False)
        state = self.api("/api/session/state")
        if state["server_id"] != self.server_id or state["session_state"] != "ready":
            raise RuntimeError("Dashboard restarted or another episode is active")
        config = self.api("/api/session/config", {"tools": tools})
        if any(
            config[k] != self.base_config[k]
            for k in (
                "model",
                "reasoning_effort",
                "max_turns",
                "max_tokens",
                "planner_timeout_s",
            )
        ):
            raise ValueError("Model or budgets changed")
        write_json(output / "config.json", config)
        results = []
        for task, seed in trials:
            if self.api("/api/session/config") != config:
                raise RuntimeError("Configuration changed")
            if any(
                hashlib.sha256((Path("robots/univtac") / n).read_bytes()).hexdigest()
                != h
                for n, h in self.hashes.items()
            ):
                raise RuntimeError("Frozen runtime source changed")
            known = {r["id"] for r in self.api("/api/runs")["runs"]}
            started = time.monotonic()
            self.status(
                phase=label,
                task=task,
                seed=seed,
                completed=len(results),
                state="starting",
            )
            self.api(
                "/api/session/messages", {"text": f"/rpent-task univtac {task} {seed}"}
            )
            while time.monotonic() - started < 4500:
                time.sleep(10)
                state = self.api("/api/session/state")
                if state["server_id"] != self.server_id:
                    raise RuntimeError("Dashboard restarted")
                fresh = [
                    r for r in self.api("/api/runs")["runs"] if r["id"] not in known
                ]
                if len(fresh) > 1:
                    raise RuntimeError("Unexpected additional episode")
                run = fresh[0] if fresh else None
                self.status(
                    phase=label,
                    task=task,
                    seed=seed,
                    completed=len(results),
                    run_id=run["id"] if run else None,
                    state=state["session_state"],
                )
                if run and run["outcome"] and state["session_state"] == "ready":
                    break
                if not run and state.get("error"):
                    raise RuntimeError(state["error"])
            else:
                raise TimeoutError(
                    "Episode not finalized; no further episode will start"
                )
            results.append(
                {
                    "task": task,
                    "seed": seed,
                    **summarize(run),
                    "batch_wall_s": round(time.monotonic() - started, 1),
                }
            )
            write_json(output / "results.json", results)
            print(json.dumps({"phase": label, **results[-1]}), flush=True)
        write_json(output / "score.json", score(results))
        return results


def development_inputs(rows):
    """Reject held-out trials before opening any evidence files."""
    if any(r["task"] != 0 for r in rows):
        raise ValueError("Maker inputs must all be task 0")
    refs = []
    for row in rows:
        root = Path(row["path"])
        config = json.loads((root / "dashboard_config.json").read_text())
        if config.get("robot") != "univtac" or config["task"]["task"] != 0:
            raise ValueError("Actual archived task must be development task 0")
        if (root / "maker-inputs").exists():
            files = {
                key: str(root / "maker-inputs" / name)
                for key, name in (
                    ("sensors", "sensors.zip"),
                    ("actions", "actions.json"),
                    ("feedback", "feedback.json"),
                )
            }
        else:
            files = export_development(root)
        refs.append(
            {
                "attempt_id": row["run_id"],
                "files": {
                    key: {
                        "path": path,
                        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    }
                    for key, path in files.items()
                },
            }
        )
    payload, images, _ = summarize_inputs(refs, "G1", frames_per_run=3)
    last = Path(rows[-1]["path"])
    payload.update(
        development_instruction=SEEN_INSTRUCTIONS["insert_hole"],
        development_outcomes=[
            {
                key: row.get(key)
                for key in (
                    "run_id",
                    "official_success",
                    "termination",
                    "decisions",
                    "input_tokens",
                    "output_tokens",
                )
            }
            for row in rows
        ],
        policy_finishes=[
            {"run_id": row["run_id"], "arguments": event["payload"]["arguments"]}
            for row in rows
            for event in (
                json.loads(line)
                for line in (Path(row["path"]) / "events.jsonl")
                .read_text()
                .splitlines()
            )
            if event["kind"] == "tool_request"
            and event["payload"].get("name") == "finish"
        ],
        consumer_prompts=json.loads((last / "prompts.json").read_text()),
        consumer_tool_declarations=json.loads(
            (last / "tool-declarations.json").read_text()
        ),
    )
    return payload, images, refs


def completion(output, system, payload, images, schema):
    output.mkdir(exist_ok=False)
    prompt_chars = len(codex_sdk.request_prompt(system, payload))
    write_json(
        output / "input-budget.json",
        {"characters": prompt_chars, "limit": MAKER_INPUT_CHARS},
    )
    if prompt_chars > MAKER_INPUT_CHARS:
        raise MakerInputBudgetError(
            f"Maker input {prompt_chars} characters exceeds local budget {MAKER_INPUT_CHARS}; no request sent"
        )
    journal = RunJournal(output)
    journal.append(
        "maker_request",
        {
            "system": system,
            "payload": payload,
            "model": "gpt-6-astra",
            "effort": "high",
            "images": images,
        },
    )
    started = time.monotonic()
    text, usage = codex_sdk.complete(
        "gpt-6-astra",
        system,
        payload,
        images,
        timeout_s=300,
        output_schema=schema,
        on_event=lambda e: journal.append("sdk_event", e),
        reasoning_effort="high",
    )
    write_json(
        output / "response.json",
        {"text": text, "usage": usage, "elapsed_s": time.monotonic() - started},
    )
    total = usage.get("total", {})
    count = total.get("output_tokens", total.get("outputTokens"))
    if count is None or count > 10000:
        raise ValueError(
            "Maker output usage missing or soft 10000-token budget exceeded"
        )
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8093")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--resume-baseline", action="store_true")
    parser.add_argument(
        "--continue-from",
        type=Path,
        help="Reuse a compatible prior batch's task-0 baseline and last validated candidate; never read test episodes",
    )
    args = parser.parse_args()
    if args.continue_from and (args.resume_baseline or args.baseline_only):
        parser.error(
            "--continue-from cannot be combined with baseline-only/resume-baseline"
        )
    if not args.resume_baseline:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "research.md").write_text(Path("research.md").read_text())
    elif list(args.output.glob("iteration-*")):
        raise ValueError("Only a completed initial baseline can be resumed")
    experiment = Experiment(args.url, args.output)
    sandbox = Sandbox("embodied-sensor:pilot")
    driver = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__),
            Path(codex_sdk.__file__),
            Path("robots/univtac/pilot/maker.py"),
            Path("robots/univtac/pilot/evidence.py"),
        )
    }
    write_json(
        args.output
        / (
            "development-driver.json"
            if args.resume_baseline
            else "baseline-driver.json"
        ),
        driver,
    )
    (
        args.output
        / ("development-driver.py" if args.resume_baseline else "baseline-driver.py")
    ).write_text(Path(__file__).read_text())
    protocol = {
        "development_seeds": [0, 1, 2],
        "max_optimizations": 5,
        "test_trials": [(t, s) for t in (1, 2) for s in range(5)],
        "sources": experiment.hashes,
        "base_config": experiment.base_config,
        "sandbox_image": sandbox.image,
        "stop": "retain 3/3 development success; >=20% mean input+output token reduction; Astra efficiency assessment agrees",
        "no_test_feedback": True,
        "one_generated_tool": True,
        "retries": 0,
        "maker_input_chars": MAKER_INPUT_CHARS,
        "tool_result_chars": TOOL_RESULT_CHARS,
        "previous_batch": str(args.continue_from) if args.continue_from else None,
    }
    if args.resume_baseline or args.continue_from:
        reference = args.continue_from or args.output
        original = json.loads((reference / "protocol.json").read_text())
        if (
            original["sources"] != protocol["sources"]
            or original["sandbox_image"] != protocol["sandbox_image"]
            or any(
                original["base_config"][key] != experiment.base_config[key]
                for key in (
                    "model",
                    "reasoning_effort",
                    "max_turns",
                    "max_tokens",
                    "planner_timeout_s",
                )
            )
        ):
            raise ValueError("Baseline runtime changed")
    if not args.resume_baseline:
        write_json(args.output / "protocol.json", protocol)
    try:
        baseline_path = (
            args.continue_from or args.output
        ) / "development-baseline/results.json"
        baseline = (
            json.loads(baseline_path.read_text())
            if args.resume_baseline or args.continue_from
            else experiment.group(
                "development-baseline", [(0, s) for s in range(3)], NATIVE
            )
        )
        if len(baseline) != 3 or {(r["task"], r["seed"]) for r in baseline} != {
            (0, s) for s in range(3)
        }:
            raise ValueError("Expected three complete development baseline trials")
        baseline_score = score(baseline)
        if args.continue_from:
            (args.output / "development-baseline").mkdir()
            write_json(args.output / "development-baseline/results.json", baseline)
            write_json(
                args.output / "development-baseline/provenance.json",
                {"reused_from": str(baseline_path), "new_simulations": 0},
            )
        if not args.resume_baseline:
            log_iteration(args.output, 0, {"score": baseline_score}, baseline_score)
        if args.baseline_only:
            experiment.status(phase="baseline_completed", completed=3)
            return
        best = {"score": baseline_score, "tool": None, "version": None, "iteration": 0}
        previous, feedback = None, {}
        last_published = None
        latest = baseline
        if args.continue_from:
            old_history = json.loads((args.continue_from / "history.json").read_text())
            validated = [r for r in old_history if "score" in r]
            if validated:
                prior = validated[-1]
                index = prior["iteration"]
                previous = json.loads(
                    (
                        args.continue_from / f"iteration-{index}/candidate.json"
                    ).read_text()
                )
                latest = json.loads(
                    (
                        args.continue_from / f"development-{index}/results.json"
                    ).read_text()
                )
                if any(row["task"] != 0 for row in latest):
                    raise ValueError("Previous batch includes non-development task")
                feedback = prior
                prior_version = digest([previous])
                if (args.library / f"{prior_version}.json").is_file():
                    last_published = prior_version
        history = []
        for iteration in range(1, 6):
            directory = args.output / f"iteration-{iteration}"
            directory.mkdir()
            experiment.status(phase="making", iteration=iteration)
            measured = None
            try:
                payload, images, refs = development_inputs(latest)
                payload.update(
                    previous_candidate=previous,
                    baseline_score=baseline_score,
                    previous_feedback=feedback,
                    required_tool_name=NAME,
                )
                payload = compact_maker_input(payload)
                wire = completion(
                    directory / "maker", MAKER, payload, images, MAKER_SCHEMA
                )
                tool = {k: wire[k] for k in ("name", "description", "source")}
                tool["parameters"] = json.loads(wire["parameters_json"])
                previous = tool
                if tool["name"] != NAME:
                    raise ValueError("Use the one stable tool name")
                validate_tools([tool])
                if len(tool["description"]) > 700:
                    raise ValueError(
                        "Tool description exceeds 700 characters; simplify the interface"
                    )
                if any(
                    word in tool["source"]
                    for word in (
                        "insert_hole",
                        "insert_tube",
                        "pull_out_key",
                        "official_success",
                        "eval_success",
                    )
                ):
                    raise ValueError("Task/evaluator identifiers are not tool inputs")
                write_json(directory / "candidate.json", tool)
                params = json.loads(wire["replay_params_json"])
                reports = []
                for ref in refs:
                    for step in (0, None):
                        frames = load_frames(ref["files"]["sensors"]["path"], step=step)
                        result = sandbox.run(tool, params, frames)
                        if (
                            result.get("error") is not None
                            or len(json.dumps(result)) > TOOL_RESULT_CHARS
                        ):
                            raise ValueError(
                                "Replay returned error or oversized result"
                            )
                        reports.append(
                            {
                                "run_id": ref["attempt_id"],
                                "steps": [f["step"] for f in frames],
                                "result": result,
                            }
                        )
                write_json(directory / "replay.json", reports)
                version = publish(
                    args.library,
                    tool,
                    {
                        "validation": "replay_passed",
                        "source_run": latest[-1]["run_id"],
                        "reason": wire["reason"],
                        "example": reports[-1]["result"],
                        "input_contract": "1..4 recorded UniVTAC RGB-D/tactile/state frames; camera metres, tactile depth mm, marker pixels, world hand pose wxyz; no evaluator",
                        "experiment_iteration": iteration,
                        **(
                            {"previous_version": last_published}
                            if last_published
                            else {}
                        ),
                    },
                )
                last_published = version
                rows = experiment.group(
                    f"development-{iteration}",
                    [(0, s) for s in range(3)],
                    NATIVE + ["generated:" + version],
                )
                candidate_score = score(rows)
                usage = valid_tool_calls(rows)
                adopted = usage["valid_calls"]
                kept = adopted > 0 and better(candidate_score, best["score"])
                measured = {
                    "score": candidate_score,
                    "adopted_calls": adopted,
                    "kept": kept,
                    "tool_execution": usage,
                }
                if kept:
                    best = {
                        "score": candidate_score,
                        "tool": tool,
                        "version": version,
                        "iteration": iteration,
                        "source_run": rows[-1]["run_id"],
                    }
                previous, latest = tool, rows
                judgement = completion(
                    directory / "assessment",
                    "Assess only these DEVELOPMENT results. Three seeds are not proof of generalization. Report token_benefit and success_benefit separately. Recommend stopping if the tool was used, all three trials succeed, and mean input+output tokens fall at least 20% versus baseline. Retaining 3/3 baseline success is sufficient for this efficiency criterion; do not claim success improvement at the ceiling. No new program or task recipe.",
                    {
                        "baseline": baseline_score,
                        "candidate": candidate_score,
                        "tool": tool,
                        "trials": rows,
                        "replay_examples": reports[-2:],
                        "tool_execution": usage,
                    },
                    [],
                    JUDGE_SCHEMA,
                )
                feedback = {
                    **measured,
                    "judgement": judgement,
                }
                history.append({"iteration": iteration, **feedback})
                write_json(directory / "evaluation.json", feedback)
                stop = adopted > 0 and early_stop(
                    candidate_score, baseline_score, judgement
                )
            except Exception as exc:
                feedback = {**(measured or {}), "error": clean(str(exc))}
                history.append({"iteration": iteration, **feedback})
                write_json(directory / "error.json", feedback)
                if input_budget_failure(exc):
                    history[-1]["failure_class"] = "maker_input_budget"
                    write_json(args.output / "history.json", history)
                    log_iteration(args.output, iteration, history[-1], baseline_score)
                    raise
                # Infrastructure loss cannot be fixed by another generated program.
                state = experiment.api("/api/session/state")
                if (
                    state["server_id"] != experiment.server_id
                    or state["session_state"] != "ready"
                ):
                    raise
                stop = False
            write_json(args.output / "history.json", history)
            write_json(args.output / "best.json", best)
            log_iteration(args.output, iteration, history[-1], baseline_score)
            if stop:
                break
        if best["tool"]:
            version = publish(
                args.library,
                best["tool"],
                {
                    "validation": "replay_passed",
                    "source_run": best["source_run"],
                    "reason": "Selected by development success then token consumption",
                    "input_contract": "1..4 recorded UniVTAC RGB-D/tactile/state frames; camera metres, tactile depth mm, marker pixels, world hand pose wxyz; no evaluator",
                    **({"previous_version": last_published} if last_published else {}),
                },
            )
            tools = NATIVE + ["generated:" + version]
        else:
            # A native-only repeat cannot establish generated-tool transfer.
            experiment.api("/api/session/config", {"tools": NATIVE})
            write_json(
                args.output / "final.json",
                {
                    "baseline": baseline_score,
                    "best_iteration": 0,
                    "iterations": len(history),
                    "test": [],
                    "reason": "No improving generated tool; held-out evaluation not started",
                },
            )
            experiment.status(
                phase="completed_no_improving_tool", completed=0, best_iteration=0
            )
            return
        config = experiment.api("/api/session/config", {"tools": tools})
        freeze = {
            "selected": best,
            "config": config,
            "tools": [
                t for t in experiment.api("/api/tools")["tools"] if t["id"] in tools
            ],
            "history": history,
            "runtime_sources": experiment.hashes,
            "development_driver": driver,
        }
        write_json(args.output / "freeze.json", freeze)
        test = experiment.group(
            "frozen-test", [(t, s) for t in (1, 2) for s in range(5)], tools
        )
        write_json(
            args.output / "final.json",
            {
                "baseline": baseline_score,
                "best_development": best["score"],
                "best_iteration": best["iteration"],
                "iterations": len(history),
                "test": test,
                "freeze_hash": digest(freeze),
            },
        )
        experiment.status(
            phase="completed", completed=10, best_iteration=best["iteration"]
        )
    except Exception as exc:
        experiment.status(phase="stopped", error=clean(str(exc)))
        raise


if __name__ == "__main__":
    main()
