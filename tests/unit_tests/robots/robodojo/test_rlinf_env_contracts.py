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

"""Agent-only observation, policy shape and CLI configuration contracts."""

from types import SimpleNamespace

import numpy as np
import pytest

from robots.robodojo import env_server


def test_server_arguments_reach_runtime_config():
    args = env_server.build_parser().parse_args(
        [
            "--task",
            "fill_pen_holder",
            "--layout",
            "8",
            "--random",
            "--env-cfg-type",
            "arx_x5",
            "--source-root",
            "/data/code",
            "--save-dir",
            "/data/output",
            "--cuda-device",
            "2",
            "--headless",
            "--max-episode-steps",
            "1200",
        ]
    )
    cfg = env_server.build_config(args)
    assert cfg.seed == 8 and not cfg.auto_reset
    assert cfg.task_config.task_name == "fill_pen_holder"
    assert cfg.task_config.source_root == "/data/code"
    assert cfg.task_config.save_dir == "/data/output"
    assert cfg.task_config.cuda_device == 2
    assert cfg.task_config.headless and cfg.task_config.random
    assert cfg.task_config.max_episode_steps == 1200
    assert (
        env_server.build_config(
            env_server.build_parser().parse_args([])
        ).task_config.source_root
        is None
    )
    with pytest.raises(ValueError, match="one environment"):
        env_server.build_config(
            env_server.build_parser().parse_args(["--num-envs", "2"])
        )


def test_policy_vectors_map_to_native_keys(agent_module):
    action = agent_module._policy_action(np.arange(14))
    assert list(action) == [
        "left_arm_joint_state",
        "right_arm_joint_state",
        "left_ee_joint_state",
        "right_ee_joint_state",
    ]
    assert [v.tolist() for v in action.values()] == [
        list(range(6)),
        list(range(6, 12)),
        [12],
        [13],
    ]
    assert agent_module._policy_action(action) is action


@pytest.mark.parametrize(
    "action",
    [
        np.zeros((1, 14)),
        np.zeros(13),
        np.zeros((50, 14)),
        np.full(14, np.nan),
    ],
)
def test_policy_shape_fails_before_motion(agent_module, make_agent, action):
    agent = make_agent(SimpleNamespace())
    with pytest.raises(ValueError, match="shape"):
        agent.step_native(action)


def test_camera_and_language_preserve_rpc_contract(make_agent):
    frames = []
    camera = {
        "color": np.zeros((2, 3, 3), dtype=np.uint8),
        "depth": np.ones((2, 3)),
        "intrinsic_matrix": np.eye(3),
        "extrinsic_matrix": np.eye(4),
    }
    env = SimpleNamespace(
        get_obs=lambda env_idx: {"vision": {"cam_head": camera}, "state": {}},
        obs_manager=SimpleNamespace(
            desc_manager=SimpleNamespace(
                get_one_description=lambda: ["Pick the object."],
            )
        ),
    )
    agent = make_agent(env, recorder=SimpleNamespace(record=frames.append))
    facade = env_server.RoboDojoEnvFacade(agent)
    meta = facade.get_camera_meta("cam_head")
    assert (meta["height"], meta["width"]) == (2, 3)
    np.testing.assert_array_equal(meta["intrinsic_matrix"], np.eye(3))
    np.testing.assert_array_equal(meta["extrinsic_matrix"], np.eye(4))
    rgb, depth = facade.render_camera("cam_head", depth=True)
    assert rgb.shape == (2, 3, 3) and depth.shape == (2, 3)
    assert (
        facade.get_obs()["instruction"]
        == facade.get_task_language()
        == "Pick the object."
    )
    assert len(frames) == 1
    with pytest.raises(IndexError):
        agent._sub_env(1)
    with pytest.raises(ValueError, match="unknown camera"):
        facade.get_camera_meta("missing")


@pytest.mark.parametrize("mode", ["dev", "eval-fair"])
@pytest.mark.parametrize("configured_limit", [2, 8])
def test_native_rpc_honors_the_stricter_step_limit(
    monkeypatch, agent_module, make_agent, mode, configured_limit
):
    limit = min(configured_limit, 5)
    calls = []
    native = SimpleNamespace(
        take_action_cnt=[limit - 1], step_lim=5, is_success=lambda env_idx: False
    )

    def apply(action, action_type, *, eval_fair):
        calls.append(action)
        native.take_action_cnt[0] += 1

    agent = make_agent(
        native,
        meta={"mode": mode, "max_episode_steps": configured_limit},
        slot=SimpleNamespace(env=native, apply_action=apply),
    )
    monkeypatch.setattr(agent_module, "_obs_dict", lambda *args: {"state": {}})
    monkeypatch.setattr(
        agent_module, "_reward_details", lambda *args: {"reward": 0, "step_limit": 5}
    )
    _, _, _, info = agent.step_native({})
    assert info["status"]["step_limit"] == limit
    assert agent.get_status()["step_limit"] == limit
    assert agent.get_reward_details()["step_limit"] == limit
    with pytest.raises(RuntimeError, match="budget"):
        agent.step_native({})
    assert calls == [{}]
    assert native.take_action_cnt == [limit]
    assert native.step_lim == 5


def test_video_recorder_keeps_rgb_and_closes_every_camera(monkeypatch, tmp_path):
    import imageio.v2 as imageio

    from robots.robodojo.agent_support import _VideoRecorder

    writers = []

    def create(path, **kwargs):
        assert kwargs["codec"] == "libx264"
        assert kwargs["pixelformat"] == "yuv420p"
        assert kwargs["ffmpeg_params"] == ["-movflags", "+faststart"]
        writer = SimpleNamespace(frames=[], closed=False)
        writer.append_data = lambda frame: writer.frames.append(frame.copy())

        def close():
            writer.closed = True

        writer.close = close
        writers.append(writer)
        return writer

    monkeypatch.setattr(imageio, "get_writer", create)
    recorder = _VideoRecorder(str(tmp_path))
    rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    rgb[:, :, 0] = 255
    recorder.record(
        {
            "vision": {
                name: {"color": rgb}
                for name in ("cam_head", "cam_left_wrist", "cam_right_wrist")
            }
        }
    )
    paths = recorder.close()
    assert len(paths) == len(writers) == 3
    assert all(writer.closed for writer in writers)
    for writer in writers:
        np.testing.assert_array_equal(writer.frames[0], rgb)
