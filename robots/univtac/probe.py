# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Headless dependency/startup probe: never constructs or resets a task."""

import argparse
import importlib
import importlib.metadata
import json
import time

from .backend import UniVTACBackend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    backend = UniVTACBackend(root=args.root, output_dir=args.output_dir)
    started = time.monotonic()
    try:
        backend.start_app()
        for name in (
            "envs._base_task",
            "envs.insert_hole",
            "envs.insert_tube",
            "envs.pull_out_key",
        ):
            importlib.import_module(name)
        import torch

        print(
            json.dumps(
                {
                    "headless_imports_passed": True,
                    "episode_started": False,
                    "elapsed_s": time.monotonic() - started,
                    "cuda_available": torch.cuda.is_available(),
                    "versions": {
                        name: importlib.metadata.version(name)
                        for name in (
                            "isaacsim",
                            "isaaclab",
                            "torch",
                            "tacex",
                            "tacex_uipc",
                            "nvidia_curobo",
                        )
                    },
                }
            ),
            flush=True,
        )
    finally:
        backend.close()


if __name__ == "__main__":
    main()
