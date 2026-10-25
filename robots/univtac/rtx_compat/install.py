# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Explicitly build a private Vulkan layer; never run it or launch a simulator."""

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

UPSTREAM = "https://github.com/KhronosGroup/Vulkan-Profiles.git"
COMMIT = "fbbca14527706745b1c899ca10fc6ad4453f2280"
TAG = "v1.4.341"


def configure(prefix: Path, python: Path) -> list[Path]:
    """Write process-scoped layer discovery and a simulator Python wrapper."""
    profile = prefix / "profiles/allocation-cap.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("allocation-cap.json"), profile)
    manifest = prefix / "xdg-data/vulkan/implicit_layer.d/VkLayer_KHRONOS_profiles.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "file_format_version": "1.2.1",
                "layer": {
                    "name": "VK_LAYER_KHRONOS_profiles",
                    "type": "GLOBAL",
                    "library_path": str(
                        prefix / "build/layer/libVkLayer_khronos_profiles.so"
                    ),
                    "api_version": "1.4.341",
                    "implementation_version": "1",
                    "description": "Private Isaac RTX allocation-limit compatibility",
                    "enable_environment": {"RPENT_VULKAN_COMPAT_ENABLE": "1"},
                    "disable_environment": {"RPENT_VULKAN_COMPAT_DISABLE": ""},
                },
            },
            indent=2,
        )
        + "\n"
    )
    env = prefix / "enable.env"
    env.write_text(
        "# Source only inside the intended simulator/query subprocess.\n"
        "export RPENT_VULKAN_COMPAT_ENABLE=1\n"
        f"export XDG_DATA_DIRS={shlex.quote(str(prefix / 'xdg-data'))}:"
        '"${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"\n'
        f"export VK_KHRONOS_PROFILES_PROFILE_DIRS={shlex.quote(str(profile.parent))}\n"
        "export VK_KHRONOS_PROFILES_PROFILE_NAME=VP_RPENT_isaac_rtx_compat\n"
        "export VK_KHRONOS_PROFILES_SIMULATE_CAPABILITIES=SIMULATE_PROPERTIES_BIT\n"
        "export VK_KHRONOS_PROFILES_DEBUG_REPORTS=DEBUG_REPORT_ERROR_BIT\n"
    )
    wrapper = prefix / "univtac-python"
    required = [
        env,
        profile,
        manifest,
        prefix / "build/layer/libVkLayer_khronos_profiles.so",
    ]
    wrapper.write_text(
        "#!/bin/sh\nset -eu\n"
        'if [ -z "${RPENT_VULKAN_COMPAT_DISABLE+x}" ]; then\n'
        f"  for file in {' '.join(shlex.quote(str(path)) for path in required)}; do\n"
        '    if [ ! -r "$file" ]; then\n'
        '      echo "Missing Isaac compatibility file: $file" >&2\n'
        "      exit 1\n"
        "    fi\n"
        "  done\n"
        f"  . {shlex.quote(str(env))}\n"
        "fi\n"
        f'exec {shlex.quote(str(python))} "$@"\n'
    )
    wrapper.chmod(0o755)
    return [profile, manifest, env, wrapper]


def main() -> None:
    """Build fixed upstream sources outside RPent and record their provenance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True, help="UniVTAC Python")
    args = parser.parse_args()
    prefix, python = (
        args.prefix.expanduser().absolute(),
        args.python.expanduser().absolute(),
    )
    if not python.is_file():
        parser.error(f"Simulator Python does not exist: {python}")
    prefix.mkdir(parents=True, exist_ok=True)
    source = prefix / "source"
    commands = []

    def run(*command: str) -> None:
        commands.append(list(command))
        subprocess.run(command, cwd=prefix, check=True)

    def git(path: Path, *command: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(path), *command], text=True
        ).strip()

    if not source.exists():
        run("git", "clone", "--depth", "1", "--branch", TAG, UPSTREAM, str(source))
    if git(source, "rev-parse", "HEAD") != COMMIT:
        raise RuntimeError(f"Refusing unexpected source revision in {source}")
    if git(source, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError(f"Refusing modified upstream sources in {source}")
    run(
        "cmake",
        "-S",
        str(source),
        "-B",
        str(prefix / "build"),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DUPDATE_DEPS=ON",
        "-DBUILD_TESTS=OFF",
        f"-DPython3_EXECUTABLE={sys.executable}",
    )
    run(
        "cmake",
        "--build",
        str(prefix / "build"),
        "--target",
        "ProfilesLayer",
        "-j",
        "4",
    )
    query = prefix / "query.c"
    shutil.copyfile(Path(__file__).with_name("query.c"), query)
    run(
        "cc",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O2",
        f"-I{source / 'external/Release/64/Vulkan-Headers/include'}",
        str(query),
        "-Wl,-l:libvulkan.so.1",
        "-o",
        str(prefix / "query"),
    )
    files = configure(prefix, python) + [
        query,
        prefix / "query",
        prefix / "build/layer/libVkLayer_khronos_profiles.so",
    ]
    dependencies = {
        path.name: git(path, "rev-parse", "HEAD")
        for path in (source / "external/Release/64").iterdir()
        if (path / ".git").exists()
    }
    (prefix / "provenance.json").write_text(
        json.dumps(
            {
                "upstream": UPSTREAM,
                "commit": COMMIT,
                "tag": TAG,
                "dependencies": dependencies,
                "commands": commands,
                "license_index": "source/LICENSE.md",
                "layer_license": "Apache-2.0",
                "simulator_python": str(python),
                "gpu_verification": "not run by installer",
                "sha256": {
                    str(path.relative_to(prefix)): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in files
                },
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
