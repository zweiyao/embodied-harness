# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""RPent RPC client; simulator dependencies remain in the separate server."""

from rpent.robots.components.env_client_base import BaseEnvClient


class UniVTACEnvClient(BaseEnvClient):
    def __init__(self, client, *, task_name: str, seed: int):
        self._client = client
        self.meta = client.call("env.get_env_meta", timeout_s=30)
        if self.meta.get("robot") != "univtac":
            raise ValueError("Expected a UniVTAC environment server")
        if self.meta.get("task_name") != task_name:
            raise ValueError("Environment server belongs to another UniVTAC task")
        self.last_obs, _ = client.call(
            "env.reset", kwargs={"task_name": task_name, "seed": seed}, timeout_s=300
        )

    def get_observation(self):
        self.last_obs = self._client.call("env.raw_obs", timeout_s=120)
        return self.last_obs

    def evaluator_state(self):
        """Trusted runner only: never register this as a model tool."""
        return self._client.call("env.evaluator_state", timeout_s=30)

    def close(self):
        return self._client.call("env.close", timeout_s=60)
