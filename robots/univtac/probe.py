# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Headless dependency/asset probe: never constructs or resets a task.

``probe-result.json`` is authoritative: Kit shutdown can exit the process before
Python returns its intended exit status. A zero exit code alone is not a pass.
"""

import argparse
import importlib
import importlib.metadata
import json
import sys
import time
import traceback
from pathlib import Path

from rpent.evaluation.result import write_json_atomic

from .backend import TASKS, UniVTACBackend


def _usd_references(path):
    from pxr import Sdf, UsdUtils

    if Sdf.Layer.FindOrOpen(str(path)) is None:
        raise ValueError("USD layer cannot be opened")
    # Includes asset-valued attributes (textures), sublayers and payloads.
    return [
        item
        for group in UsdUtils.ExtractExternalReferences(str(path))
        for item in group
    ]


def _mdl_search_paths():
    import carb.settings
    import carb.tokens

    settings = carb.settings.get_settings()
    tokens = carb.tokens.get_tokens_interface()
    return [
        Path(tokens.resolve(value.strip())).resolve()
        for kind in ("required", "templates")
        for value in (settings.get(f"/renderer/mdl/searchPaths/{kind}") or "").split(
            ";"
        )
        if value.strip()
    ]


def check_local_assets(
    root,
    *,
    importer=importlib.import_module,
    usd_references=_usd_references,
    mdl_search_paths=(),
):
    """Check the actual gsmini config and its local USD dependency graph.

    The pinned configuration loader only builds configs; calling it unbound does
    not instantiate a Task or initialize robot, camera or tactile simulation.
    """
    root = Path(root).resolve()
    report = {
        "tasks": [],
        "files": [],
        "errors": [],
        "remote_references_unchecked": [],
        "renderer_search_paths": [str(path) for path in mdl_search_paths],
        "renderer_resolutions": [],
    }
    visited = set()

    def visit(value, anchor, source):
        if "://" in str(value):
            report["remote_references_unchecked"].append(str(value))
            return
        asset = Path(value).expanduser()
        path = (asset if asset.is_absolute() else anchor / asset).resolve()
        # Match Kit's registered module roots, including namespaces such as
        # gltf/pbr.mdl. An explicit ./ or ../ path remains a local dependency.
        if (
            not path.exists()
            and asset.suffix == ".mdl"
            and not asset.is_absolute()
            and not str(value).startswith(("./", "../"))
        ):
            for search_root in mdl_search_paths:
                resolved = (Path(search_root) / asset).resolve()
                if resolved.is_file():
                    path = resolved
                    report["renderer_resolutions"].append(
                        {
                            "asset": str(value),
                            "path": str(path),
                            "search_root": str(search_root),
                            "source": source,
                        }
                    )
                    break
        if path in visited:
            return
        visited.add(path)
        try:
            if not path.is_file():
                raise FileNotFoundError("required local asset is missing")
            with path.open("rb") as stream:
                header = stream.read(512)
            if not header:
                raise ValueError("required local asset is empty")
            if header.startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise ValueError("Git LFS pointer has not been downloaded")
            report["files"].append(
                {"path": str(path), "size_bytes": path.stat().st_size}
            )
            if path.suffix.lower() in (".usd", ".usda", ".usdc"):
                for reference in usd_references(path):
                    visit(reference, path.parent, str(path))
        except Exception as exc:
            report["errors"].append(
                {"path": str(path), "source": source, "error": str(exc)}
            )

    for name in TASKS:
        module = importer(f"envs.{name}")
        if Path(module.__file__).resolve() != root / "envs" / f"{name}.py":
            raise RuntimeError("Wrong envs package imported")
        cfg = module.TaskCfg()
        cfg.tactile_sensor_type = "gsmini"  # Same sensor selected by backend.reset.
        cfg = module.Task.load_robot_and_sensors(None, cfg)
        usd_path = cfg.robot.robot.spawn.usd_path
        visit(usd_path, root, f"{name}.robot.spawn.usd_path")
        visit(cfg.plate.spawn.usd_path, root, f"{name}.plate.spawn.usd_path")
        folders = []
        for tactile in cfg.robot.tactiles:
            optical = tactile.sensor_cfg.optical_sim_cfg
            folder = Path(optical.calib_folder_path)
            folders.append(str(folder))
            # Native TaximImpl/TaximTorch load all five, even with_shadow=False.
            for filename in (
                "params.json",
                "polycalib.npz",
                "gelmap.npy",
                "dataPack.npz",
                "shadowTable.npz",
            ):
                visit(folder / filename, root, f"{name}.{tactile.name}.optical_sim_cfg")
        report["tasks"].append(
            {
                "task": name,
                "sensor": cfg.tactile_sensor_type,
                "robot_usd": str(usd_path),
                "calibration_folders": folders,
            }
        )
    report["passed"] = not report["errors"]
    return report


def run_probe(*, root, output_dir, backend_factory=UniVTACBackend):
    """Persist diagnostics before shutting down Kit, including startup failures."""
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "probe_passed": False,
        "headless_imports_passed": False,
        "local_assets_passed": False,
        "episode_started": False,
        "status": "running",
    }
    write_json_atomic(output / "probe-result.json", result)
    started, backend = time.monotonic(), None
    try:
        backend = backend_factory(root=root, output_dir=output)
        backend.start_app()
        importlib.import_module("envs._base_task")
        for name in TASKS:
            importlib.import_module(f"envs.{name}")
        result["headless_imports_passed"] = True
        result["assets"] = check_local_assets(
            root, mdl_search_paths=_mdl_search_paths()
        )
        result["local_assets_passed"] = result["assets"]["passed"]
        if not result["local_assets_passed"]:
            raise RuntimeError(
                "Required local assets are missing, invalid, or Git LFS pointers"
            )
        import torch

        result.update(
            cuda_available=torch.cuda.is_available(),
            versions={
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
            probe_passed=True,
            status="passed",
        )
    except BaseException as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        details = traceback.format_exc()
        (output / "probe-error.txt").write_text(details)
        sys.stderr.write(details)
        sys.stderr.flush()
    finally:
        result["elapsed_s"] = time.monotonic() - started
        write_json_atomic(output / "probe-result.json", result)
        print(json.dumps(result), flush=True)
        if backend is not None:
            backend.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output-dir", required=True)
    result = run_probe(**vars(parser.parse_args()))
    return 0 if result["probe_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
