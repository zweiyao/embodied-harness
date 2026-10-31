# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Shared instructions for both planners; no hidden task geometry."""

from rpent.prompt.utils import BulletList


def system_prompt(variables=None):
    selected = (variables or {}).get("manual_tools", [])
    names = {item["name"] for item in selected}
    generated = any(item["origin"] == "generated" for item in selected)
    return {
        "ROLE": "Complete the instructed contact manipulation task. "
        "The object starts grasped near the target; determine its alignment and progress from observations.",
        "OBSERVATION": "Use the returned camera images, metric depth, bilateral tactile images and measured robot state. "
        "Match observations by recorded step number and compare motion and contact changes after each action. "
        "The initial tactile reference may already be loaded. Pixel or marker displacement is not calibrated force; "
        "missing data means unknown.",
        "CONTROL": (
            "Command the Panda hand in world coordinates: position in metres, unit quaternion wxyz, "
            "and gripper opening from 0 (closed) to 1 (open). Execute short targets, then inspect the returned "
            "measured pose and object motion. If progress stops, reassess alignment and contact before repeating."
            if "move_eef" in names
            else None
        ),
        "AVAILABLE TOOLS": BulletList(
            [
                f"{item['name']}: {item['description'].strip().splitlines()[0]}"
                for item in selected
            ]
        ),
        "TOOL USE": "Use the declared tools to observe and act; their schemas specify arguments and limits. "
        "Base decisions on returned sensor evidence and robot state. "
        "Every model response counts toward the decision budget, including perception calls and corrections."
        + (
            " Generated perception tools provide measurements and evidence; assess their applicability "
            "before using them to choose an action. Their output is not an official success verdict."
            if generated
            else ""
        ),
        "FINISH": "Call finish when observable evidence supports completion or recovery is exhausted. "
        "These insertion and extraction tasks do not require releasing the object. "
        "Report the outcome and supporting evidence; the official evaluator records success separately.",
    }


def user_prompt(variables=None):
    return {"TASK": "{{instruction}}", "GUIDANCE": "{{task_guidance}}"}
