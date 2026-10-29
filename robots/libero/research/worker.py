# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Container-only entry point; never import generated code in the host runner."""

import contextlib
import importlib.util
import json
import resource
import sys

import numpy as np

resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with np.load("/input/arrays.npz", allow_pickle=False) as archive:

    def decode(value):
        if isinstance(value, dict):
            if set(value) == {"__array__"}:
                return archive[value["__array__"]]
            return {k: decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [decode(v) for v in value]
        return value

    with open("/input/input.json") as file:
        data = decode(json.load(file))
# Redirect ordinary debug prints; only the final result is the protocol output.
with contextlib.redirect_stdout(sys.stderr):
    spec = importlib.util.spec_from_file_location("candidate", "/input/candidate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run(data["frames"], data["params"])
print(json.dumps(result, allow_nan=False))
