# Perception tool research / 感知工具闭环

Perception research runs through the original RPent CLI, planner, toolkit and
Dashboard. The outer research runner selects episodes and frozen libraries;
it does not implement an action loop. Run simulation, validation and tests on
the experiment host, from its project workspace.

本入口复用 RPent 的运行服务与 8 个动作工具。控制器内的停止判断保留，模型拿到的
动作结果包含新观测、执行步数、动作块计数和执行错误，不含成功判断。`pi0_pick` 和 `pi0_doubled` 直接使用 RPent 原默认参数，不再由研究配置覆盖动作块预算。可选控制参数在模型 schema 中固定为原默认值，继续隔离内部成功判断和 oracle。

## Interfaces / 接口

The four basic sensor tools are `view_env_state`, `view_camera_meta`,
`back_project` (one pixel) and `segment` (SAM3 text or positive-point mask, score, box and overlay).
Only calibrated 256×256 RGB, metric depth, depth-derived world coordinates,
camera calibration, proprioception and recorded SAM3 masks reach generated tools.
They receive up to four frames. Model-facing file tools, task recipes, object
inventories, oracle success, simulator APIs and controller success labels are absent.
The actor uses RPent's API planner and teacher exploration uses its Codex planner
with the same registered sensor/action boundary. Tool proposals use isolated
JSON inference after episodes. The teacher receives native outcomes only offline.

基础感知工具为上述 4 个。新工具是 `run(frames, params)` Python 函数，只在 Docker
中运行（无网络、无 GPU、只读输入、内存/时间限制）。可用 NumPy；分割由模型先调用
固定 SAM3 工具完成，新工具可以读取对应帧的 mask。文字和点选均复用 RPent Sam3Client，叠加图复用 RPent 的绘制函数并在下一次模型决策时展示；不把文字标签当作已验证物体身份。第一版不允许工具内部调用视觉大模型。
没有工具数量上限；按一个失败假设修订一组相关工具。完整库按 SHA256 保存，批次内冻结。

## Run / 运行

Enable the mode explicitly in either CLI or Dashboard; `[]` selects an empty
generated library. Start with `view_env_state`; motion outputs carry subsequent
observations. Each TaskRun freezes its loaded library and saves `sensor-trace.json`
and `research-report.json` alongside RPent's transcript, video and states.
Only the evaluator report contains native success. Model `finish` text and the
Dashboard's completed-run status are not the task success metric.

```bash
printf '[]\n' > /tmp/empty-sensor-library.json
rpent --robot libero --libero-type pro --dashboard \
  --planner api --model openai-chat:Qwen3.8-27B \
  --base-url http://127.0.0.1:18121/v1 --memory-profile local \
  --sensor-library /tmp/empty-sensor-library.json \
  --max-turns 24 --max-episode-steps 2000
# In the native Dashboard: /rpent-task libero_10 0 2
```

For native Codex exploration, use `--planner codex --model gpt-6-astra` and omit
`--base-url`. The research toolkit excludes planner file tools and inherited MCP
servers; Codex can call only RPent's registered MCP tools. Do not combine this
mode with `--explore`, task memory or direct-action exposure.

Build the small sandbox image on the experiment host:

```bash
docker build -t embodied-sensor:pilot -f robots/libero/research/Dockerfile .
```

If the machine already has the two images referenced by `Dockerfile.offline`,
that Dockerfile builds the same Python/NumPy interface without downloads. Only
the Python runtime and NumPy are copied from the large robotics image; simulator
assets and source are absent. The actual image hash is recorded per experiment.

Set `RPENT_REPO_ROOT`, source the existing simulation environment, and copy
`pilot.json` to a local configuration outside version control. Set live VLA/SAM3
endpoints to borrow those services; null starts owned services. Never pass a
physical robot endpoint. Set the actor's OpenAI-compatible URL/model; optional
`key_env` names an environment variable rather than storing a secret.

Astra uses `codex_sdk` on the experiment host, reusing RPent's installed
`openai-codex` SDK and bundled runtime. Authenticate on that same host:

```bash
codex login --device-auth
codex login status
```

If `codex` is not on PATH, the SDK's `codex_cli_bin.bundled_codex_path()` returns
the installed executable. The SDK sends images and sanitized reports directly
from the experiment host; there is no SSH forwarding or local inference relay.
Proposal requests use fresh, ephemeral, read-only sessions without MCP or built-in
tools. Native exploration uses RPent MCP in an isolated Codex home. Both share
only that host's normal credentials and provider settings.

远程直接登录和调用 Codex；本机不转发模型请求。已有的 `codex_relay` 仅用于读取旧实验
配置，新实验使用 `codex_sdk`。更换后端会改变实验协议，需要重新运行探索与基线。

```bash
python -m robots.libero.research.runner --config /path/to/pilot.local.json --output /path/to/new-run
```

`--stop-after-baseline` pauses after teacher exploration and actor baseline,
writing `pause.json` before any proposal is requested. The relay also supports
`--pause-proposals` as an operator guard for an already-running experiment.

`pilot.json` chooses LIBERO-10 tasks 0/3/9, explores seeds 0–1, validates 2–4 and
reserves 5–9. The runner rejects repeated initial-state hashes, including aliases
caused by seed modulo. Every iteration saves the teacher proposal, candidate
version, actor trajectories, usage, native outcomes and promotion decision.
Acceptance requires more validation successes and no task-total regression.
Errors reject promotion. Rejection keeps the incumbent and feeds evidence to the
next iteration. This small development gate is not a statistical significance test.

留出集只在完成工具选择后单独运行：在本地配置写入确定的 `start_version`，再用
`--heldout` 与全新输出目录。这个入口不调用 teacher，也不升级工具库。
批量运行的原始 RPent 状态位于各局 `native/`，仅供人工审计；不要提供给在线模型。
重复使用验证集会过拟合，跨任务/跨模型泛化需要后续独立划分；本阶段不据此宣称泛化。

No monetary savings are inferred from token counts: request token usage and wall
time are recorded, while pricing/GPU accounting is left to subsequent analysis.
A clean run means framework integration, not necessarily native task success.

## Checks / 检查

```bash
pytest tests/unit_tests/robots/libero/research -q
```

Offline tests cover sensor isolation, fixed control parameters, versions and
rollback, paired promotion, JSON parsing and initial-state split collisions.
Real Docker, model and simulation checks are separate and recorded on the project
board. A short run with one task, one seed per split and bounded turns is intended
for integration before the full pilot. No generated library is preloaded.

Device-code login is described in the
[official authentication guide](https://learn.chatgpt.com/docs/auth#login-on-headless-devices).

To continue a baseline checkpoint, use a new output directory and
`--baseline-from /path/to/paused-run`. The runner checks the config, prompt,
controller, container and initial-state identities before reusing reports.
Only development reports and explicitly named sensor PNGs are copied. The paused
run stays intact. Teacher feedback includes labeled images from exploration,
baseline and the previous candidate; heldout images are never included.

Call `view_env_state` once initially; motions supply updated observations.
The pilot allows 24 model requests and 2000
environment steps. These are separate from the unchanged RPent primitive defaults.
Old configs containing `action_chunks` are rejected rather than silently changing
control behavior. Recalibrate the baseline before comparing generated libraries.
The native planner protocol differs from the legacy JSON decision loop; its
protocol identity prevents reuse of old baseline checkpoints.
