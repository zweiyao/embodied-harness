# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Run an already-reserved environment smoke, never a model score.

The native expert reads hidden task state. Its observations and outcomes are
diagnostics only and are deliberately not registered as maker inputs.
"""

from __future__ import annotations

import argparse
import json
import signal
import time
import traceback
from pathlib import Path

from robots.univtac.backend import UniVTACBackend, save_native_frame
from robots.univtac.pilot import Pilot
from rpent.evaluation.result import write_json_atomic


def load_reservation(output_dir: Path):
    """Require a fresh script reservation; do not create or charge a new slot."""
    record = json.loads((output_dir / "pilot-attempt.json").read_text())
    if record["output_dir"] != str(output_dir):
        raise ValueError("Pilot reservation belongs to another output directory")
    pilot = Pilot(record["pilot_root"])
    cell = pilot._cell(record["cell"]["id"])
    if record["cell"] != cell or cell["stage"] != "smoke" or cell["model"] != "script":
        raise ValueError("Only the two fixed script smoke cells may use this runner")

    def validate(events):
        attempt = pilot._attempt(events, record["attempt_id"])
        if (attempt["session_id"], attempt["cell"], attempt["freeze_id"]) != (
            str(output_dir),
            cell["id"],
            record["freeze_id"],
        ):
            raise ValueError("Pilot metadata differs from its ledger reservation")
        if record["attempt_id"] in pilot._finished(events):
            raise ValueError("This reserved episode has already finished")
        return None, None

    pilot._transaction(validate)
    return pilot, record


def run_smoke(*, root, output_dir, device="cuda:0", backend_factory=UniVTACBackend):
    """Reset once, register the scene, hold once, then run the official expert."""
    output_dir = Path(output_dir).resolve()
    pilot, record = load_reservation(output_dir)
    # An interrupted or concurrently running attempt cannot silently reset again.
    with (output_dir / "smoke-started.json").open("x") as stream:
        json.dump(
            {"attempt_id": record["attempt_id"], "started_at": time.time()}, stream
        )
    started = time.monotonic()
    backend = None
    reset_complete = False
    outcome = {
        "termination_reason": "setup_failure",
        "official_success": None,
        "native_success": None,
        "scripted_expert": True,
        "script_only": True,
        "model_score": False,
        "maker_inputs_excluded": True,
        "expert_uses_model_command_budget": False,
        "eef_commands_attempted": 0,
        "eef_commands_executed": 0,
    }
    try:
        cell = record["cell"]
        backend = backend_factory(
            root=root,
            output_dir=output_dir / "simulator",
            task_name=cell["task"],
            seed=cell["seed"],
            device=device,
        )
        observation, _ = backend.reset()
        reset_complete = True
        initial = backend.evaluator_state()
        fingerprint = pilot.record_scene(record["attempt_id"], initial["scene"])
        record["scene_fingerprint"] = fingerprint
        write_json_atomic(output_dir / "pilot-attempt.json", record)
        write_json_atomic(output_dir / "smoke-initial-evaluator.json", initial)
        save_native_frame(output_dir / "smoke-initial-sensors.npz", observation)
        state = observation["state"]
        command = [*state["eef_pose_wxyz"].tolist(), state["gripper"]]
        outcome["eef_commands_attempted"] = 1
        _, _, _, _, receipt = backend.step(command)
        outcome["eef_commands_executed"] = receipt["native_action_delta"]
        outcome["hold_receipt"] = receipt
        write_json_atomic(
            output_dir / "smoke-hold.json",
            {
                "command": command,
                "receipt": receipt,
                "purpose": "One unchanged EEF target verifies the generic IK interface",
            },
        )
        if not receipt["exec_success"]:
            raise RuntimeError(
                "Generic hold command failed; native expert was not started"
            )
        write_json_atomic(
            output_dir / "smoke-expert.json",
            {
                "method": "native Task.play_once",
                "uses_hidden_task_state": True,
                "part_of_model_evaluation": False,
                "model_command_budget_applies": False,
            },
        )
        backend.task.play_once()
        official = bool(backend.task.check_success())
        outcome.update(official_success=official, native_success=official)
        final = backend.evaluator_state()
        # play_once is the expert path and does not update eval_success, which is
        # normally set by take_action. Preserve both rather than inventing a flag.
        final["official_predicate_after_expert"] = official
        write_json_atomic(output_dir / "smoke-final-evaluator.json", final)
        save_native_frame(output_dir / "smoke-final-sensors.npz", backend.observation())
        outcome.update(
            termination_reason="completed" if official else "failed",
            scene_fingerprint=fingerprint,
            hold_receipt=receipt,
            evaluator_path=str(output_dir / "smoke-final-evaluator.json"),
            video_path=final["video_path"],
        )
        backend.finish_recording()
    except BaseException as exc:
        reason = "failed" if reset_complete else "setup_failure"
        if isinstance(exc, TimeoutError):
            reason = "timeout"
        elif isinstance(exc, (KeyboardInterrupt, SystemExit)):
            reason = "aborted"
        outcome.update(termination_reason=reason, error=f"{type(exc).__name__}: {exc}")
        (output_dir / "smoke-error.txt").write_text(traceback.format_exc())
    finally:
        if reset_complete:
            try:
                final = backend.evaluator_state()
                outcome["physics_steps_after_reset"] = final["physics_step"]
                outcome["native_action_count"] = final["control_step"]
            except Exception as exc:
                outcome["accounting_error"] = str(exc)
        if backend is not None:
            try:
                backend.finish_recording()
            except BaseException as exc:
                outcome["recording_error"] = str(exc)
                if outcome["termination_reason"] == "completed":
                    outcome["termination_reason"] = "failed"
        outcome["elapsed_s"] = time.monotonic() - started
        # Persist the outcome before Kit shutdown, which may terminate its Python
        # process. The ledger is authoritative and receives exactly one finish.
        write_json_atomic(output_dir / "smoke-outcome.json", outcome)
        pilot.finish_episode(record["attempt_id"], outcome)
        record["outcome"] = outcome
        write_json_atomic(output_dir / "pilot-attempt.json", record)
        if backend is not None:
            backend.close()
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()

    def deadline_reached(_signum, _frame):
        raise TimeoutError("Smoke supervisor wall-clock deadline reached")

    # The independent supervisor sends this only to the Python child, allowing
    # the child to flush video and finish its ledger before any forced shutdown.
    signal.signal(signal.SIGALRM, deadline_reached)
    result = run_smoke(**vars(args))
    print(json.dumps(result))
    return 0 if result["termination_reason"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
