# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""One JSON decision protocol for both the exploring teacher and the actor."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.request

ACTOR_PROMPT = """Control a simulated robot to complete the given instruction. Select exactly one provided tool per turn. Return only a JSON object {"tool": "name", "arguments": {...}}. Inspect current sensory evidence and tool outputs, adapt after failures, and call finish when done or stuck. The current RGB and proprioception are supplied automatically each turn; do not spend a turn reading the same view_env_state again. The first two images are agentview then wrist, 256x256 with row zero at top. Additional images, if any, visualize the preceding tool result. A segment overlay shows the selected region, not a verified semantic identity. Use point-based segment when text selects an ambiguous region. Motion execution counts describe progress; using the full chunk budget is not proof of success or failure. Motion coordinates are world metres. Use the fixed pick primitive to grasp, then move and release; use contact primitives for articulated objects. Generated sensor tools, when available, compute on the last four recorded sensor frames and existing segmentation masks. No external files or task recipes are available."""

TEACHER_PROMPT = """Improve a reusable perception-tool library from development robot trajectories and evaluation feedback. Return only JSON {"hypothesis": "a falsifiable failure explanation", "tools": [full replacement library]}. Each tool is {"name": "sensor_snake_case", "description": "when and how to use it, including argument units", "parameters": JSON object schema, "source": Python source defining run(frames, params) -> JSON dict}. Prefix names sensor_. Python has numpy; no network, GPU, motion API, files other than sensor input, or external model calls. Tools should compute evidence, geometry or temporal relations, not encode task IDs, scene coordinates, recipes or known success labels. Prefer one coherent failure hypothesis per revision; no fixed tool-count limit. Retain useful existing tools. Do not change controller, actor instructions, evaluation or initial states. Native terminal outcomes in reports are offline feedback, unavailable inside the tool. Do not claim evaluation results you have not seen.
Input contract: frames is oldest to newest, at most four frames. Each frame has step, proprio (robot0_eef_pos, robot0_eef_quat, robot0_gripper_qpos), cameras (agentview and wrist), masks. Each camera has rgb uint8[256,256,3], depth float32[256,256] in metres, world float32[256,256,3], calibration (intrinsic_K, extrinsic_cam2world, height,width when available). Masks is keyed by m0,m1,... within each step; value {camera,mask: bool[256,256],score}. Actor must call segment first to create masks. Params should identify needed mask IDs/steps/regions; validate absence and return uncertainty. Return concise JSON values, no arrays/images. Empty masks and short history are normal. Use robust summaries and explicit frame/camera identities. Your entire library is frozen during an evaluation batch."""


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("model response must be a JSON object")
    return result


class Model:
    """Call the remote Codex SDK, an actor endpoint, or a legacy relay."""

    def __init__(self, config: dict):
        self.config = config

    def complete(
        self, system: str, payload: dict, images: list[bytes]
    ) -> tuple[dict, dict]:
        config = self.config
        if config["kind"] == "codex_sdk":
            from .codex_sdk import complete

            started = time.monotonic()
            answer, usage = complete(config["model"], system, payload, images)
            return parse_json(answer), {
                "model": config["model"],
                "seconds": round(time.monotonic() - started, 3),
                "usage": usage,
            }
        encoded = [base64.b64encode(img).decode() for img in images]
        text = json.dumps(payload, allow_nan=False)
        if config["kind"] == "codex_relay":
            url = config["url"].rstrip("/") + "/complete"
            body = {
                "system": system,
                "payload": payload,
                "images": encoded,
                "model": config["model"],
            }
        else:
            url = config["url"].rstrip("/") + "/chat/completions"
            content = [{"type": "text", "text": text}] + [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + data},
                }
                for data in encoded
            ]
            body = {
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                "temperature": 0,
                "max_tokens": config.get("max_tokens", 4096),
            }
        headers = {"Content-Type": "application/json"}
        if config.get("key_env"):
            headers["Authorization"] = "Bearer " + os.environ[config["key_env"]]
        started = time.monotonic()
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=headers
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.load(response)
        if config["kind"] == "codex_relay":
            answer, usage = result["answer"], result.get("usage", {})
        else:
            answer = parse_json(result["choices"][0]["message"]["content"])
            usage = result.get("usage", {})
        return answer, {
            "model": config["model"],
            "seconds": round(time.monotonic() - started, 3),
            "usage": usage,
        }
