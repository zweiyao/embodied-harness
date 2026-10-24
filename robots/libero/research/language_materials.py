# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Freeze an explicitly selected prose-only guidance package for one run."""

import hashlib
import json
import shutil
from pathlib import Path


def freeze_materials(source, output_dir, prompt_vars):
    """Verify the package before copying it; leave the published corpus intact."""
    source = Path(source).resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    for name in ("system.md", "user.md", "guide.md", "memory/MEMORY.md"):
        if name not in manifest["files"]:
            raise ValueError(f"Missing language material: {name}")
    for name, expected in manifest["files"].items():
        path = (source / name).resolve()
        if not path.is_relative_to(source):
            raise ValueError(f"Invalid language material path: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Changed language material: {name}")
    target = Path(output_dir) / "language-materials"
    target.mkdir(parents=True)
    # Copy only the verified files, not adjacent source archives or old recipes.
    for name, expected in manifest["files"].items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Language material changed while copying: {name}")
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    prompt_vars.update(
        language_materials=str(target),
        memory_dir=str(target / "memory"),
        memory_version=manifest["version"],
    )


def material_prompt(variables, name):
    """Return the already frozen system or user prose for prompt rendering."""
    return (Path(variables["language_materials"]) / name).read_text()
