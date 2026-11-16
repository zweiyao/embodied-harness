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

"""Checkpoint action conversion before native joint/gripper dispatch."""

import numpy as np
import pytest

from robots.robodojo.policy import policy_actions_to_native


def test_checkpoint_channels_reach_the_correct_native_controls(agent_module):
    state = np.array([[1, 2, 3, 4, 5, 6, 0.9, 7, 8, 9, 10, 11, 12, 0.1]])
    deltas = np.array(
        [
            [
                [
                    0.1,
                    0.2,
                    0.3,
                    0.4,
                    0.5,
                    0.6,
                    0.25,
                    -0.1,
                    -0.2,
                    -0.3,
                    -0.4,
                    -0.5,
                    -0.6,
                    0.75,
                ]
            ]
        ]
    )
    original = deltas.copy()
    native = agent_module._policy_action(policy_actions_to_native(deltas, state)[0, 0])
    np.testing.assert_allclose(
        native["left_arm_joint_state"], [1.1, 2.2, 3.3, 4.4, 5.5, 6.6]
    )
    np.testing.assert_allclose(
        native["right_arm_joint_state"], [6.9, 7.8, 8.7, 9.6, 10.5, 11.4]
    )
    np.testing.assert_allclose(native["left_ee_joint_state"], [0.25])
    np.testing.assert_allclose(native["right_ee_joint_state"], [0.75])
    np.testing.assert_array_equal(deltas, original)


def test_each_batch_uses_its_own_raw_joint_state():
    states = np.array(
        [[1] * 6 + [0.8] + [2] * 6 + [0.2], [3] * 6 + [0.6] + [4] * 6 + [0.4]]
    )
    actions = np.zeros((2, 50, 14), dtype=np.float32)
    actions[..., 6] = 0.25
    actions[..., 13] = 0.75
    native = policy_actions_to_native(actions, states)
    for batch, left, right in [(0, 1, 2), (1, 3, 4)]:
        np.testing.assert_array_equal(native[batch, :, :6], np.full((50, 6), left))
        np.testing.assert_array_equal(native[batch, :, 6:12], np.full((50, 6), right))
        np.testing.assert_array_equal(
            native[batch, :, 12:], np.tile([0.25, 0.75], (50, 1))
        )


@pytest.mark.parametrize(
    "actions,states",
    [
        (np.zeros((1, 50, 32)), np.zeros((1, 14))),
        (np.zeros((50, 14)), np.zeros((1, 14))),
        (np.full((1, 50, 14), np.nan), np.zeros((1, 14))),
        (np.zeros((1, 50, 14)), np.zeros((2, 14))),
        (np.zeros((1, 50, 14)), np.full((1, 14), np.inf)),
    ],
)
def test_invalid_predictions_fail_before_native_control(actions, states):
    with pytest.raises(ValueError, match="RoboDojo policy"):
        policy_actions_to_native(actions, states)
