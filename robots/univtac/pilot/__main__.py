# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Inspect and update a pilot ledger without launching a simulator or model."""

import argparse
import json
from pathlib import Path

from . import Pilot


def main() -> None:
    """Dispatch one explicitly requested protocol operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("summary")
    commands.add_parser("manifest")
    amendment = commands.add_parser("amend-budget")
    amendment.add_argument("--reason", required=True, help="User authorization reason")
    reserve = commands.add_parser("reserve")
    reserve.add_argument("cell")
    reserve.add_argument("session")
    reserve.add_argument("--freeze")
    for name in ("scene", "finish", "finish-offline"):
        command = commands.add_parser(name)
        command.add_argument("attempt")
        command.add_argument("payload", type=Path)
    validation = commands.add_parser("validate-interface")
    validation.add_argument("attempt")
    validation.add_argument("evidence", type=Path)
    decision = validation.add_mutually_exclusive_group(required=True)
    decision.add_argument("--passed", dest="passed", action="store_true")
    decision.add_argument("--failed", dest="passed", action="store_false")
    freeze = commands.add_parser("freeze")
    freeze.add_argument("payload", type=Path)
    inputs = commands.add_parser("maker-inputs")
    inputs.add_argument("variant", choices=("G0", "G1"))
    inputs.add_argument("attempts", nargs="+")
    offline = commands.add_parser("reserve-offline")
    offline.add_argument("purpose")
    offline.add_argument("variant", choices=("G0", "G1"))
    offline.add_argument("attempts", nargs="+")
    offline.add_argument("--maker-budget", type=Path)
    offline.add_argument("--max-tokens", type=int, default=0)
    args = parser.parse_args()
    pilot = Pilot.create(args.root) if args.command == "init" else Pilot(args.root)
    if args.command in ("init", "manifest"):
        result = pilot.manifest
    elif args.command == "summary":
        result = pilot.summary()
    elif args.command == "amend-budget":
        result = pilot.amend_budget(args.reason)
    elif args.command == "reserve":
        result = pilot.reserve_episode(args.cell, args.session, args.freeze)
    elif args.command == "validate-interface":
        result = pilot.record_interface_validation(
            args.attempt, args.passed, args.evidence
        )
    elif args.command == "maker-inputs":
        result = pilot.maker_inputs(args.variant, args.attempts)
    elif args.command == "reserve-offline":
        result = pilot.reserve_offline(
            args.purpose,
            args.variant,
            args.attempts,
            maker_budget=json.loads(args.maker_budget.read_text())
            if args.maker_budget
            else None,
            max_tokens=args.max_tokens,
        )
    else:
        payload = json.loads(args.payload.read_text())
        if args.command == "freeze":
            result = pilot.freeze(payload)
        elif args.command == "scene":
            result = pilot.record_scene(args.attempt, payload)
        elif args.command == "finish-offline":
            result = pilot.finish_offline(args.attempt, payload)
        else:
            result = pilot.finish_episode(args.attempt, payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
