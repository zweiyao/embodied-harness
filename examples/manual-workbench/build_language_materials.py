# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Build a separate natural-language corpus from a backed-up LIBERO corpus.

Run on the experiment host. Published files and controller code are never edited.
Original audit values remain historical observations, not current scene targets.
"""

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

import yaml

OPERATIONS = {
    "pi0_pick": "grasp and lift the identified object",
    "pi0_doubled": "perform a bounded learned contact manipulation",
    "pi0_end_to_end": "perform a learned full manipulation sequence",
    "move_to": "move the end effector to the intended location",
    "move_pose": "move while coordinating position and orientation",
    "set_gripper": "adjust the gripper opening",
    "rotate_wrist": "rotate the wrist about the vertical axis",
    "rotate_pitch": "tilt the wrist",
    "release": "open the gripper to let go of the held object",
    "back_project": "recover world coordinates from calibrated image and depth",
    "segment": "identify a visible region and estimate its geometry",
    "view_env_state": "inspect a recorded scene and robot state",
    "view_camera_meta": "inspect the camera calibration",
    "read_image": "inspect a recorded image",
    "read_text_file": "read the relevant document",
    "write_text_file": "save a written record",
    "list_dir": "look through the available documents",
    "finish": "end the attempt with an honest result",
    "reset": "restart the episode (historical action; forbidden in this evaluation)",
}

LABELS = {
    "max_chunks": "maximum number of policy action chunks",
    "chunks_used": "number of policy action chunks used",
    "steps": "controller updates",
    "max_steps": "maximum controller updates",
    "steps_used": "controller updates used",
    "step_clip": "per-update motion limit in the associated motion units",
    "lift_thresh": "lift detection threshold in metres",
    "gripper_closed_thresh": "closed-grip detection threshold in metres",
    "gripper_open_thresh": "open-grip detection threshold in metres",
    "descent_thresh": "descent detection threshold in metres",
    "gripper": "gripper command",
    "prompt": "instruction",
    "target_yaw": "desired wrist yaw in radians",
    "delta_yaw": "change in wrist yaw in radians",
    "target_pitch": "desired wrist pitch in radians",
    "delta_pitch": "change in wrist pitch in radians",
    "ori_tol": "orientation tolerance in radians",
    "tol": "motion tolerance in the associated motion units",
    "action_scale": "controller translation scaling in metres",
    "xyz": "historical world position in metres",
    "world_xyz": "measured world position in metres",
    "eef_y": "end-effector y coordinate",
    "object_y": "object y coordinate",
    "eef_z": "end-effector height",
    "eef_x": "end-effector x coordinate",
    "terminated": "official task completion",
    "libero_terminated": "official benchmark completion",
    "truncated": "environment time limit reached",
    "robot0_eef_pos": "end-effector world position",
    "robot0_eef_quat": "end-effector orientation quaternion",
    "robot0_gripper_qpos": "finger joint positions",
    "agentview_high": "high-resolution calibrated external-camera image",
    "wrist_high": "high-resolution calibrated wrist-camera image",
    "agentview": "external camera",
    "wrist": "wrist camera",
    "row_range": "image row interval",
    "col_range": "image column interval",
    "z_min": "minimum world height",
    "z_max": "maximum world height",
    "z_band": "world-height interval",
    "min_score": "minimum region confidence",
    "task_language": "task instruction",
    "strategy_notes": "strategy and lessons",
    "command_sequence": "historical action sequence",
    "pick_result": "historical grasp evidence",
    "success": "reported operation outcome",
}


def slug(name):
    return name.replace("pi0", "learned-grasp").replace("sam3", "region-estimation")


def label(key):
    return LABELS.get(key, key.replace("_", " "))


def prose(text):
    """Translate identifiers and call notation while retaining physical evidence."""
    text = str(text)
    text = re.sub(
        r"(?:robots|resources)/libero/guides/[\w.-]+",
        "the historical manipulation guide",
        text,
    )
    text = re.sub(
        r"(?:resources/)?memory/libero/[\w/.-]+",
        "the historical experience library",
        text,
    )
    text = re.sub(
        r"([\w-]*(?:pi0|sam3)[\w-]*)(?=\.md|\]\])", lambda m: slug(m[1]), text
    )
    # Published references become narrative pages; no executable recipes are linked.
    text = re.sub(r"([\w-]+)_recipe\.jsonl", r"\1.md", text)
    text = re.sub(r"([\w-]+)\.json\b", r"\1.md", text)
    text = re.sub(
        r"\bset_gripper\s+\+?1(?:\s+steps\s*=?\s*(\d+(?:-\d+)?))?",
        lambda m: (
            "close and maintain the grip"
            + (f" for {m[1]} controller updates" if m[1] else "")
        ),
        text,
    )
    text = re.sub(
        r"\bset_gripper\s+-1(?:\s+steps\s*=?\s*(\d+(?:-\d+)?))?",
        lambda m: (
            "open the gripper" + (f" for {m[1]} controller updates" if m[1] else "")
        ),
        text,
    )
    text = re.sub(r"\b(?:gripper)\s*[:=]?\s*\+?1\b", "the gripper kept closed", text)
    text = re.sub(r"\b(?:gripper)\s*[:=]?\s*-1\b", "the gripper kept open", text)

    # Convert simple Python-style calls into operation descriptions and named values.
    names = "|".join(map(re.escape, OPERATIONS))
    pattern = re.compile(r"\b(" + names + r")\(([^()]*?)\)")

    def call(match):
        try:
            node = ast.parse(match.group(0), mode="eval").body
            details = [scalar(ast.literal_eval(a)) for a in node.args]
            details += [
                f"{label(k.arg)}: {scalar(ast.literal_eval(k.value))}"
                for k in node.keywords
            ]
            return OPERATIONS[match[1]] + ("; " + "; ".join(details) if details else "")
        except (ValueError, SyntaxError, TypeError):
            return OPERATIONS[match[1]] + "; " + match[2]

    text = pattern.sub(call, text)
    # Name-value annotations become historical settings in words.
    for old, new in LABELS.items():
        text = re.sub(r"\b" + re.escape(old) + r"\s*[:=]\s*", new + ": ", text)
    text = text.replace(
        "agentview_high.png", "the calibrated high-resolution external-camera image"
    )
    text = text.replace(
        "wrist_high.png", "the calibrated high-resolution wrist-camera image"
    )
    # Bare common English words remain ordinary prose, not tool identifiers.
    for old, new in {**OPERATIONS, **LABELS}.items():
        if old in {
            "release",
            "segment",
            "finish",
            "reset",
            "prompt",
            "success",
            "wrist",
            "gripper",
        }:
            continue
        text = re.sub(r"\b" + re.escape(old) + r"\b", new, text)
    text = re.sub(
        r"\b(?:Pi0(?:\.5)?|pi0(?:\.5)?)\b", "the learned manipulation policy", text
    )
    text = text.replace("SAM3", "visual region estimation")
    text = re.sub(
        r"\b([A-Za-z][A-Za-z0-9_]*_[A-Za-z0-9_]+)\s*=",
        lambda m: label(m[1]) + ": ",
        text,
    )
    text = (
        text.replace("```jsonc", "")
        .replace("```json", "")
        .replace("```python", "")
        .replace("```", "")
    )
    text = text.replace("`", "")
    text = text.replace(".reported operation outcome", " reported operation outcome")
    text = text.replace(
        "## Magic numbers", "## Historical numeric settings and applicability"
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def scalar(value):
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return "not recorded"
    if isinstance(value, list):
        return "(" + ", ".join(scalar(v) for v in value) + ")"
    if isinstance(value, dict):
        return "; ".join(f"{label(k)}: {scalar(v)}" for k, v in value.items())
    return prose(value)


def action_text(item):
    operation = item.get("action", item.get("tool", "historical operation"))
    parts = [OPERATIONS.get(operation, prose(operation))]
    for key, value in item.items():
        if key in {"action", "tool", "step"}:
            continue
        if key == "gripper" and value in (-1, 1):
            parts.append(
                "keep the gripper closed" if value == 1 else "keep the gripper open"
            )
        else:
            parts.append(f"{label(key)}: {scalar(value)}")
    return "; ".join(parts) + "."


def describe(value, indent=0):
    """Render structured audit evidence as labeled prose, never callable JSON."""
    prefix = "  " * indent
    lines = []
    if isinstance(value, dict):
        if isinstance(value.get("action"), str):
            return prefix + "- " + action_text(value)
        for key, item in value.items():
            heading = prose(label(key))
            if isinstance(item, dict) or (
                isinstance(item, list)
                and any(isinstance(v, (dict, list)) for v in item)
            ):
                lines += [prefix + "- " + heading + ":", describe(item, indent + 1)]
            else:
                lines.append(prefix + f"- {heading}: {scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, list):
                lines.append(prefix + "- " + scalar(item))
            else:
                lines.append(describe(item, indent))
    else:
        lines.append(prefix + "- " + scalar(value))
    return "\n".join(lines)


SYSTEM = """You are controlling one LIBERO simulation episode using visual observations,
calibrated depth and robot proprioception. The current task instruction in the
recorded scene determines the target and goal. Complete that task physically.

Read {{language_materials}}/guide.md and the index at {{memory_dir}}/MEMORY.md.
Consult relevant experience by its described objects, relation and failure mode,
not by an apparent match of task numbers. Historical positions must be measured
again in this scene. Published experience is read-only.

Guidance describes desired evidence and physical behavior, not a preferred API.
Choose from the enabled tool declarations according to what information or action
you need. Native and added perception tools are equally eligible when applicable.
The declarations specify actual argument names, units, defaults and limits;
historical numeric settings are observations, not instructions to override them.

Use only the provided experimental tools. Do not obtain hidden simulator object
poses, read benchmark scene definitions, bypass the tools through files or shell,
teleport objects, or restart the episode. Recovery within the same episode is
allowed. Inspect action feedback before making subsequent dependent decisions.
The planner reasons between recorded action observations, not from a live stream.

Distinguish grasp evidence, physical placement, and the official task completion
signal. Do not claim completion from a plausible-looking image alone. If unable
to continue, end honestly with the remaining uncertainty. The service records
the experiment automatically; any additional summary must reflect the actual
observations and experience consulted. Follow the current run's time and decision
budgets; an historical success does not establish reliability in this scene.
"""

USER = """Experiment: {{suite}}, task {{task}}, seed {{seed}}.
Output directory: {{output_dir}}.
Inspect the initial recorded scene to obtain the actual task instruction.
Read the language guide and the relevant experience, identify and localize the
target and destination in this scene, then perform the task. Select the available
interfaces from their declarations; no historical interface is prescribed.
"""

GUIDE = """# Visual manipulation guide

## Identify, then measure
Use the high-resolution external-camera image for object identity, labels and
scene relations. Similar packages require attention to shape and readable labels.
Use the wrist view to refine the geometry of the same candidate after approaching;
do not silently switch identity based on a close-up. For an open container, the
wrist view may help distinguish its interior from the rim. If two views disagree,
check identity, image orientation, pixel resolution, camera and observation step.

Calibrated external and wrist RGB images have corresponding depth and world
coordinates. The policy image can have a different orientation and must not be
used as though it were a calibrated geometry image. High images are normally
1024 by 1024 and low images 256 by 256; use the resolution and coordinate convention
declared by the chosen interface. Depth-derived positions are visible surface
points, not automatically object centres or grasp sites. Compare several interior
samples away from silhouettes, thin edges and backgrounds. Large patch spread
can indicate mixed surfaces. All world coordinates use metres. Wrist calibration
changes with the observation step. Recorded views do not advance or refresh the
simulation; the latest scene normally follows the last completed action.

## Use experience as evidence
Experience has a global layer, task-family lessons and historical task narratives.
Read the index and choose by actual task language and objects. A matching number
does not ensure the same task. A missing exact reference is not a reason to invent
one; relevant general lessons remain useful. Historical action sequences and
numeric ranges describe what happened, including failures. Re-measure all scene
coordinates and verify that the historical conditions apply. Confidence based on
one episode remains limited. Old records may include multiple attempts; this run
allows only one episode and no restart.

## Grasp and maintain control
Approach the identified target without crossing surrounding clutter. Near-target
views can refine position; an isolated object may need less refinement. Some
learned grasp behaviors already contain an approach, so pre-positioning is not
universally beneficial. Use a bounded grasp attempt and inspect its result.
Confirm the correct object is held through its visible displacement, hand-relative
position and finger opening. A nonzero opening alone is not proof of identity.
A reported operation outcome based on hand motion can disagree with visual grasp
evidence; task completion is a separate question. A learned grasp behavior may
continue transporting the object, so inspect where it actually stopped.

For bowls and mugs, a visible centre can be an empty opening; choose a suitable
graspable rim or handle. Historical bowl offsets are shape-specific evidence, not
a universal mug or bottle offset. Keep the gripper closed throughout transport.
Check each selected action's opening default; a pose change must not accidentally
open the hand. Grip tightening and speed depend on shape and stability. Fingers
fully closed with no lifted object suggest an empty grasp.

## Carry, align and place
Estimate the held object's extent and its offset from the end effector. Keep its
lowest part clear of obstacles during lateral travel. Use intermediate waypoints
when a direct route crosses clutter or exceeds a safe reach. Avoid fast transport
of loosely held objects. Object-frame and spatial-suite table heights differ;
measure the local support surface rather than copying a historical height.

For a basket or cavity, identify the free interior, rim height and support surface.
A median over a liner or rim may not locate the free opening. Align the held object,
including its grasp offset, over the interior before lowering or releasing. Tall
objects may require extra carry clearance; historical high drops only apply when
the footprint is safely inside the cavity. Avoid pushing against the rim or liner,
which can move the container. Measure again after contact or displacement.

After release, allow settling and retreat with the hand open without dragging the
object. A perched or bridging object may require regrasping and a small deeper
seating correction. Some predicates become true while an object is still held;
others only after release and retreat. Report these observations separately.
For cabinet, drawer, knob or microwave interactions, account for contact direction,
opening geometry and wrist orientation. Persistent position error may be a reach
or contact constraint; coordinated position and orientation changes can help, but
never substitute a claim of success for an observed state change.

## Check the result
Inspect the next recorded image and robot state after an action. Verify target
identity, held status, placement and the official goal flag. Spatial relation words
depend on the task frame; do not confuse image-left with robot-left. When placement
looks correct but the goal remains false, check identity and the requested relation,
not only the motion. Preserve uncertainty when depth, occlusion or grasp geometry
does not support a conclusion.
"""


def build(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    target.mkdir(parents=True, exist_ok=False)
    provenance = {}
    entries = []
    for scope in ("global", "task-family"):
        for original in sorted((source / scope).glob("*.md")):
            text = original.read_text()
            meta = {}
            if text.startswith("---\n"):
                _, front, text = text.split("---", 2)
                meta = yaml.safe_load(front) or {}
            title = (
                meta.get("title")
                or meta.get("task_language")
                or original.stem.replace("_", " ")
            )
            name = scope + "/" + slug(original.name)
            # Retain applicability, evidence, confidence and original narrative.
            body = f"# {prose(title)}\n\n" + describe(meta) + "\n\n" + prose(text)
            destination = target / "memory" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(body.strip() + "\n")
            provenance["memory/" + name] = [str(original.relative_to(source))]
            entries.append((name, prose(title)))
    for original in sorted((source / "task-specific").glob("*.json")):
        data = json.loads(original.read_text())
        for key in tuple(data):
            if key.startswith("memory_"):
                # Historical paths describe old environments, not this package.
                data[key] = (
                    "Historical source/access bookkeeping is preserved in the original backup. Consult the current experience index for available documents."
                )
        recipe = original.with_name(original.stem + "_recipe.jsonl")
        title = (
            data.get("perturbed_task_language")
            or data.get("task_language")
            or original.stem
        )
        body = f"# Historical task: {prose(title)}\n\n"
        body += "Historical evidence only. Positions belong to the recorded scene; re-localize in the current scene. Prior restarts, if mentioned, are not allowed in the current single episode.\n\n"
        body += describe(data) + "\n"
        originals = [str(original.relative_to(source))]
        if recipe.exists():
            body += "\n## Historical sequence in words\n\n"
            for i, line in enumerate(recipe.read_text().splitlines(), 1):
                if line.strip():
                    body += f"{i}. {action_text(json.loads(line))}\n"
            originals.append(str(recipe.relative_to(source)))
        name = "memory/task-specific/" + original.stem + ".md"
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body)
        provenance[name] = originals
        entries.append(("task-specific/" + original.stem + ".md", prose(title)))
    index = "# Experience index\n\nChoose by actual object, relation and failure mode, not by task number. These are historical lessons, not commands to replay. Read only the relevant narratives.\n\n"
    index += "\n".join(f"- [{name}]({name}): {title}" for name, title in entries) + "\n"
    (target / "memory/MEMORY.md").write_text(index)
    for name, text in (("system.md", SYSTEM), ("user.md", USER), ("guide.md", GUIDE)):
        (target / name).write_text(text)
    files = {
        str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(target.rglob("*.md"))
    }
    version = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    manifest = {
        "version": "language-" + version[:16],
        "files": files,
        "source_corpus": str(source),
        "source_sha256": {
            str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(source.rglob("*"))
            if p.is_file()
        },
        "provenance": provenance,
        "excluded_from_planner": "Flash replay JSON plans and executable JSON/JSONL originals remain in the complete backup. The 75 audit/recipe pairs are represented as narratives. Original guide mechanics were consolidated into guide.md.",
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "version": manifest["version"],
                "narratives": len(entries),
                "files": len(files),
                "target": str(target),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()
    build(args.source, args.target)
