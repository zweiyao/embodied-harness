# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Decode the released ARX-X5 Pi0.5 checkpoint at the native action boundary."""

from __future__ import annotations

import numpy as np


def policy_actions_to_native(actions: np.ndarray, states: np.ndarray) -> np.ndarray:
    """Restore joint deltas and convert checkpoint 7+7 order to native 12+2.

    RLinf has already unnormalized and unpadded the 32-D model output to
    ``[batch, chunk, 14]``. Both it and the raw ``[batch, 14]`` states use
    left arm/gripper, then right arm/gripper. Grippers remain absolute.
    The native vector contains both arms followed by both grippers.
    """
    actions = np.asarray(actions, dtype=np.float32)
    states = np.asarray(states, dtype=np.float32)
    if actions.ndim != 3 or actions.shape[-1] != 14 or not np.isfinite(actions).all():
        raise ValueError("RoboDojo policy actions must be finite [batch, chunk, 14]")
    if states.shape != (actions.shape[0], 14) or not np.isfinite(states).all():
        raise ValueError("RoboDojo policy states must be finite [batch, 14]")
    absolute = actions.copy()
    absolute[..., :6] += states[:, None, :6]
    absolute[..., 7:13] += states[:, None, 7:13]
    return np.concatenate(
        (
            absolute[..., :6],
            absolute[..., 7:13],
            absolute[..., 6:7],
            absolute[..., 13:14],
        ),
        axis=-1,
    )
