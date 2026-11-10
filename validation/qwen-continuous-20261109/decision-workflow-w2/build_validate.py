# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Build and validate the approved isolated W2 prose package, without a policy."""

import copy
import hashlib
import json
import stat
from datetime import datetime, timezone
from pathlib import Path

from robots.libero.research.language_materials import freeze_materials
from robots.libero.research.manual import availability_prompt
from robots.libero.robot_spec import get_robot_spec
from rpent.dashboard.workbench import native_catalog
from rpent.utils.config import get_repo_root

ROOT = Path(__file__).resolve().parent
BASE = Path("/home/zwy/work/embodied_harness")
PARENT = BASE / "language-materials/qwen-evidence-v3-readable"
HANDOFF = json.loads(
    (ROOT.parent / "orientation-feedback/source-handoff.json").read_text()
)
SOURCE = Path(HANDOFF["source_root"])
PLAN = json.loads(
    (BASE / "experiments/qwen-continuous-20261109/iteration-06/plan.json").read_text()
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def snapshot(root):
    return {
        str(p.relative_to(root)): digest(p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def source_snapshot():
    return {
        name: digest((SOURCE / name).read_bytes())
        for name in HANDOFF["source_files_sha256"]
    }


def normalize_rendered_system(text, condition, task):
    return text.replace(str(ROOT / "freeze-check" / f"{condition}-t{task}"), "<RUN>")


def variables(task, output):
    return {
        "suite": "libero_10_task",
        "task": task,
        "seed": 0,
        "output_dir": str(output),
        "recipe_tag": f"libero_10_task_t{task}_s0",
        "reference_tag": f"10_task_t{task}_s0",
        "memory_dir": str(PARENT / "memory"),
        "memory_inbox": str(ROOT / "unused-inbox"),
        "memory_profile": "hf",
        "mode": "eval",
        "session_number": 1,
        "session_max": 1,
        "enable_direct_action": False,
    }


spec = get_robot_spec()


def default_prompts():
    result = {}
    for mode in ("eval", "explore", "native"):
        values = variables(0, ROOT / "default-not-started")
        values["mode"] = mode
        if mode == "native":
            values["sensor_library"] = PLAN["candidate_library"]
        result[mode] = {
            kind: spec.prompts.render(kind, variables=values)
            for kind in ("system", "user")
        }
    return result


assert get_repo_root() == SOURCE
assert Path(freeze_materials.__code__.co_filename).resolve().is_relative_to(SOURCE)
assert source_snapshot() == HANDOFF["source_files_sha256"]
assert len(HANDOFF["source_files_sha256"]) == 303
metadata = json.loads((ROOT / "draft-metadata.json").read_text())
after = (ROOT / "user-after.draft.md").read_bytes()
assert digest(after) == metadata["after_sha256"]
assert digest((ROOT / "user-before.md").read_bytes()) == metadata["before_sha256"]
assert digest((PARENT / "user.md").read_bytes()) == metadata["before_sha256"]
parent_before = snapshot(PARENT)
parent_manifest = json.loads((PARENT / "manifest.json").read_text())
assert set(parent_before) == set(parent_manifest["files"]) | {"manifest.json"}
assert all(
    parent_before[name] == value for name, value in parent_manifest["files"].items()
)
defaults_before = default_prompts()
catalog_before = native_catalog()
assert len(PLAN["config"]["tools"]) == len(PLAN["tool_names"]) == 18
selected = [{"name": name} for name in PLAN["tool_names"]]
selection_prompt = availability_prompt(selected)

manifest = copy.deepcopy(parent_manifest)
manifest["files"]["user.md"] = digest(after)
content_id = digest(json.dumps(manifest["files"], sort_keys=True).encode())
manifest["version"] = "qwen-decision-w2-" + content_id[:12]
package = BASE / "language-materials" / manifest["version"]
assert not package.exists(), "Never overwrite an existing material package"
package.mkdir()
for name in manifest["files"]:
    target = package / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(after if name == "user.md" else (PARENT / name).read_bytes())
save(package / "manifest.json", manifest)
for path in package.rglob("*"):
    path.chmod(0o555 if path.is_dir() else 0o444)
package.chmod(0o555)

published = snapshot(package)
assert set(published) == set(parent_before)
changed_files = [
    name for name in parent_before if parent_before[name] != published[name]
]
assert sorted(changed_files) == ["manifest.json", "user.md"]
restored_manifest = copy.deepcopy(manifest)
restored_manifest["version"] = parent_manifest["version"]
restored_manifest["files"]["user.md"] = parent_manifest["files"]["user.md"]
assert restored_manifest == parent_manifest
assert all(
    not (stat.S_IMODE(p.stat().st_mode) & 0o222) for p in [package, *package.rglob("*")]
)

rendered = {}
for task in (4, 0):
    for condition, material in (("parent", PARENT), ("w2", package)):
        output = ROOT / "freeze-check" / f"{condition}-t{task}"
        values = variables(task, output)
        freeze_materials(material, output, values)
        frozen = Path(values["language_materials"])
        assert snapshot(frozen) == snapshot(material)
        pair = {
            kind: spec.prompts.render(kind, variables=values)
            for kind in ("system", "user")
        }
        assert "{{" not in pair["system"] + pair["user"]
        assert str(frozen / "guide.md") in pair["system"]
        assert str(frozen / "memory/MEMORY.md") in pair["system"]
        if condition == "w2":
            assert str(frozen / "guide.md") in pair["user"]
            assert str(frozen / "memory/MEMORY.md") in pair["user"]
            assert "NEXT=<enabled action or finish>; NEED=" in pair["user"]
            assert f"task {task}, seed 0" in pair["user"]
        pair["system"] = selection_prompt + pair["system"]
        rendered[f"{condition}-t{task}"] = pair
        for kind, text in pair.items():
            (output / f"rendered-{kind}.md").write_text(text)
    assert normalize_rendered_system(
        rendered[f"parent-t{task}"]["system"], "parent", task
    ) == normalize_rendered_system(rendered[f"w2-t{task}"]["system"], "w2", task)

assert parent_before == snapshot(PARENT)
assert source_snapshot() == HANDOFF["source_files_sha256"]
assert published == snapshot(package)
assert defaults_before == default_prompts()
assert catalog_before == native_catalog()
save(ROOT / "default-prompts.json", defaults_before)
save(ROOT / "parent-files.json", parent_before)
save(ROOT / "material-manifest.json", manifest)
save(ROOT / "catalog.json", catalog_before)
validation = {
    "passed": True,
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "changed_package_files": sorted(changed_files),
    "changed_manifest_fields": ["version", "files.user.md"],
    "parent_files_unchanged": len(parent_before),
    "source_files_unchanged": len(HANDOFF["source_files_sha256"]),
    "real_freeze_and_render_cases": list(rendered),
    "normalized_system_equal_per_task": True,
    "default_prompt_cases_unchanged": len(defaults_before) * 2,
    "native_catalog_unchanged": True,
    "read_only_package": True,
    "before_user_words": len((ROOT / "user-before.md").read_text().split()),
    "after_user_words": len(after.decode().split()),
    "model_requests": 0,
    "vla_requests": 0,
    "simulator_actions": 0,
}
save(ROOT / "validation.json", validation)
handoff = {
    "source_root": str(SOURCE),
    "source_handoff_path": str(
        ROOT.parent / "orientation-feedback/source-handoff.json"
    ),
    "parent_package_path": str(PARENT),
    "parent_package_version": parent_manifest["version"],
    "parent_files_sha256": parent_before,
    "package_path": str(package),
    "package_version": manifest["version"],
    "material_files_sha256": manifest["files"],
    "manifest_sha256": published["manifest.json"],
    "selected_tool_ids": PLAN["config"]["tools"],
    "selected_tool_names": PLAN["tool_names"],
    "validation_passed": True,
    "validation_path": str(ROOT / "validation.json"),
    "policy_experiments_started": False,
}
save(ROOT / "material-handoff.json", handoff)
print(json.dumps({"package_path": str(package), "validation": validation}, indent=2))
