# UniVTAC backend

This optional backend is separate from LIBERO and runs in its own Python 3.10
environment. RPent's planner runs in its existing environment and communicates
through the existing loopback RPC transport. It does not load a VLA or alter
LIBERO controllers.

The shared API/Codex system prompt lives in `prompt_bundle.py`. It describes
role, observations, control, available tools, tool use and completion. The tool
overview is rendered from the run's frozen selection; complete arguments and
descriptions are also sent as tool declarations. Deselected tools are omitted,
and generated-tool guidance appears only when one is selected. The dashboard
does not prepend the legacy LIBERO guide override. Changes apply to new runs;
archived `prompts.json` files retain the original input.

Task text uses the pinned upstream `seen` instructions verbatim for all three
tasks. `instructions.py` holds their snapshot so the planner does not require
an Isaac installation. Before native reset, the backend reads the upstream
`instructions/<task>.json` and checks exact equality with that snapshot; drift
is an error. In particular, the key task requires rotation to mechanical
resistance before extraction, and the tube task includes its diameters and
inclined surface. Task-specific experimental guidance remains a separate
`GUIDANCE` section. Historical runs using the earlier paraphrases are unchanged
and should be distinguished from runs using official instructions.

The live console reads the completed run's `outcome.environment_success`, just
like the history page. A clean planner exit or an environment termination flag
is not a success verdict. Missing results display as unrecorded; the environment
returning to its waiting state after cleanup does not mean the task failed.

Pinned sources:

- UniVTAC `0dafa10262e22f486f160a55d6f11aeab12d8e7b`, Apache-2.0 according to
  its LICENSE (the upstream README currently says MIT).
- Isaac Sim 4.5.0; Isaac Lab v2.1.1,
  `90b79bb2d44feb8d833f260f2bf37da3487180ba`.
- cuRobo v0.7.7, `0a50de1ba72db304195d59d9d0b1ed269696047f`.
- TacEx and libuipc are the modified copies bundled in the pinned UniVTAC
  checkout. Replacing them with unrelated releases is unsupported.
- Generic Panda helpers: TacTalent
  `75441c18c3054b6032c4923f4047b9deaef26694`; attribution/license in `_panda/`.

The server accepts `insert_hole`, `insert_tube`, and `pull_out_key`. Native
reset, pre-grasp initialization, success checks, early stops and 300-command
limits remain unchanged. The adapter additionally limits attempted valid EEF
commands to 300, counting IK rejections. Each absolute world-frame Panda **hand** command uses
local cuRobo IK, rejects joint changes above 0.15 rad, then applies one native
joint-position action with up to two 120 Hz physics steps. This is the native
kinematic `force=True` position interface, not a force controller. A batch has
1–5 commands. Native termination can stop a command after its first physics
step. IK rejection returns a failure receipt and consumes no simulator action;
the adapter still charges the attempted command and the runner charges the
model response. The 60-response budget belongs
to the experiment runner.

`env.reset`, `step`, `chunk_step`, camera metadata/rendering and `raw_obs`
follow RPent's existing facade. `env.evaluator_state` is for the trusted
runner only and must never become a model tool. Each server is owned by one
episode; launch another process to change tasks. CLI example:

```sh
PYTHONPATH=/home/zwy/work/harnessvla \
  /home/zwy/work/embodied_harness/external/univtac-env/bin/python \
  -m robots.univtac.env_server \
  --root /home/zwy/work/embodied_harness/external/UniVTAC \
  --output-dir /home/zwy/work/embodied_harness/experiments/univtac-native \
  --task-name insert_hole --seed 0 --port 18760
```

Starting the server does not start an episode. The first reset does. The
`--parent-watch` enables graceful cleanup when an owning daemon closes its
stdin. `env.close` only flushes recording and blocks further motion; daemon
shutdown closes Kit after the RPC response. The `robots.univtac.probe` module starts the headless app and imports task classes
without constructing/resetting them; it is an infrastructure check, not a
robotics success test.

Agent observations contain only head/wrist RGB-depth, camera calibration,
left/right tactile RGB/native depth/marker measurements and robot joint/hand
state. Marker displacement is current minus initial marker pixel coordinates.
Native tracking quality is unavailable. `reference_rgb` is the actual first
post-reset, already-in-contact frame (`episode_initial_contact`), not a
no-contact calibration image. No actor/target poses, expert atom tags, rewards
or official success labels are exposed to the model. Pose metadata explicitly
uses metres, world axes and wxyz quaternions; normalized gripper 1 corresponds
to single-finger opening 0.039 m.

Camera depth is in metres. Native tactile `depth` is sensor-camera depth in
millimetres, not indentation depth or force. Image sizes are `[height, width]`;
marker positions are `(x, y)` pixels, origin top-left, x right and y down.
`simulation_time_s` and `physics_dt` describe simulator time; `timestamp` is
wall time and includes API waiting.

Native recordings, raw actor state, initial gel vertices, initial sensor
hashes, RNG state/hashes, physics settings and asset hashes are archived
separately under a unique native run directory. The recording-only task subclass
persists every executed physical step as a numeric NPZ in `evaluator-frames/`,
because upstream eval mode itself writes only video. Native videos are
`native/video/<seed>.mp4`, encoded at 10 fps (not physical real time). Private
metadata records the reset video offset and each raw frame's video index.
They are evaluator data, not
model inputs. The scene fingerprint is **not a restorable simulator snapshot**:
UIPC solver/contact warm-start state and renderer internals are not captured.
Matching seeds alone cannot certify matched scenes. Recording/fixture tests
also do not demonstrate task success or a gain from generated tools.

See [INSTALL.md](INSTALL.md) for isolated deployment and the recorded build
dependency workaround. Headless imports, scripted smoke and model episodes
are separate verification stages.
