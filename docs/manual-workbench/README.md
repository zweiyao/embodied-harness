# RPent manual tool workbench

Enabled for LIBERO, UniVTAC and Flexiv dashboards by
`RPENT_WORKBENCH=/absolute/config.json`. Set `robot` to the matching environment
(omitting it retains the LIBERO default). Configuration contains `runs_root`,
`library_root`, the existing setup-page
`setup` object and `models` profiles (`id`, `label`, `planner`, `model`, optional
`base_url`, `key_file`, `codex_home`, `reasoning_effort`). Keys stay in private
server files. The selected profile's probe must pass before starting an episode.

All model profiles inherit the server process's network environment. The
workbench does not set, clear or switch proxy variables. Configure networking on
the remote host; for a systemd service, configure its service environment rather
than only an interactive SSH shell, and restart the service when idle.

Use the standalone [remote network script](../../deploy/remote-network.sh) on the
Linux host before launching an experiment:

```bash
source /home/zwy/work/embodied_harness/remote-network.sh direct
# Or select an already-running remote loopback HTTP proxy:
source /home/zwy/work/embodied_harness/remote-network.sh proxy http://127.0.0.1:17997
source /home/zwy/work/embodied_harness/remote-network.sh status
```

Choose one mode; the proxy example requires a working listener at that address.
The script updates the current shell and user systemd manager. It does not start
a proxy, modify Mac networking, or restart existing services. Existing processes
retain their environment; restart only the intended idle dashboard when needed.
Explicit service-level environment overrides take precedence over manager values
and must be removed separately. Experiment and probe scripts inherit this choice;
they must not load the switcher or override proxy/IP-family behavior themselves.
Archived experiment scripts describe historical conditions and must be cleaned
before reuse. Local-only MCP transport safeguards in the original harness remain
separate from model-provider networking.

Use `/` to select the model and tools, `/tools` to inspect source and metadata,
`/console` to run, and `/runs` to inspect history. Saving/copying a configuration
does not start it. New tools are never selected automatically. `finish` is
required; select at most one version of each name. Native action signatures,
controller code and automatic image feedback are retained. Native prompts and
memory are the default; the language-guidance experiment below explicitly
replaces their model-facing text.

## Shared component catalog / 全部工具与每轮选择

All three environments reuse the same catalog, picker, detail dialog, frozen
selection and planner allowlist. Each runtime still owns its observation and
control adapters. A shared Python function signature does not imply compatible
camera fields, coordinate frames, units, tactile sensors or action semantics.

Set `RPENT_TOOL_CATALOG` on each dashboard service to a server-owned JSON file:

```json
[
  {"robot": "libero", "library_root": "/absolute/libero-library"},
  {"robot": "univtac", "library_root": "/absolute/univtac-library"},
  {"robot": "flexiv", "control_mode": "rdk", "library_root": "/absolute/flexiv-library"}
]
```

Each service uses its own Workbench configuration for its current environment;
the other entries add read-only descriptions and sources to the shared catalog.
Library directories must exist. No remote robot, simulator or planner is opened
to browse them. Without this file, the current environment's catalog remains
available. The Flexiv control mode comes from its server launch configuration.

在“全部组件”中可查看三种环境的控制、感知和辅助工具；“本环境可选”只显示已接入
当前环境的接口。每张卡片标明来源、已接入环境、用途、参数和源码。不兼容的工具
仍可查看，但不能勾选，页面会解释缺少的适配。通用辅助工具只在已有运行时支持时
合并展示；例如 UniVTAC 不开放文件读取，以免读到评测真值。

开始页的全选、清空、恢复原生默认仅作用于本环境可选工具。`finish` 必需，新工具
默认不选；依赖缺失、未知版本和跨环境接口在提交配置时直接报错。选中清单和源码
在实验启动时冻结，之后编辑配置只影响下一轮。两个 planner 都受同一清单限制。
取消感知工具不会关闭动作后自动返回的图像。

Flexiv 使用同一套 Workbench 模型配置和日志机制；启动参数的 `--output-dir` 必须
位于该配置的 `runs_root` 下。原生控制接口和机械臂启用流程保持不变；选择了当前
硬件状态不能提供的接口时会明确失败，不会静默漏掉工具。只读实验请取消控制工具。
对齐／接触工具通过 Flexiv 观测适配器读取定位查询与实际 TCP/力记录，在原有 Docker
沙箱执行。它可以被手动选入实验；接入和回放通过均不代表任务成功率提升。

## Language-guidance experiment

Back up the complete published memory directory, original guides, prompt sources
and deployment configuration before building a separate package:

```bash
python examples/manual-workbench/build_language_materials.py \
  /path/to/published/corpus /path/to/new-language-package
```

This package retains global and task-family lessons and converts historical
audit/recipe pairs into Markdown narratives. Numeric observations, task identity,
failure conditions and confidence remain historical evidence. Tool identifiers
and call syntax become descriptions of physical operations and measurements.
The original guides are consolidated into a language guide; this changes prompt
length and wording as well as tool references, so it is not a name-only ablation.
Flash replay programs remain in the original backup and are not planner guidance.

Set the server workbench configuration's `language_materials` to the package's
absolute directory and reload the server only when idle. Remove that field and
reload to return to native guidance. Every new task verifies the package manifest
and copies its documents into the run's `language-materials/` directory. The
copied system/user text and copied memory root are used together. Original memory
is not overwritten; later package edits do not affect a running task. Actual
tool declarations, controllers and the user's tool selection remain unchanged.
No experiment is started and no generated tool is automatically selected by
this switch. Historical runs retain their original prompts and records.

## Create a perception tool from a run

Write candidate JSON with `name` (starts with `sensor_`), `description`, JSON
Schema `parameters`, and Python `source` defining `run(frames, params)`. Write
metadata JSON with `source_run`, `reason`, `input_contract`, optional
`dependencies` (tool names) and `previous_version` (full hash).

From the remote project environment:

```bash
python -m robots.libero.research.manual_library \
  --library /path/to/tool-library/manual \
  --candidate /path/to/candidate.json --metadata /path/to/metadata.json \
  --replay-run /path/to/recorded/run --step 3 --params '{"camera":"agentview"}'
```

Publication validates the schema/source without executing it on the host.
Replay runs inside the existing no-network Docker sandbox. A replay failure
does not publish a new version. Omitting replay publishes as `unverified`.
Refresh the tool-library page to see it, inspect its source, and select it on
the next setup page. Publishing a replacement removes older versions of the same
tool from the library and stores a source diff when `previous_version` is supplied.
Historical experiments retain their frozen source and versions; publication does
not change selected tools or a running experiment. Different tool names remain
independent. A selection referring to a removed version must be updated manually.
Replay success and real invocation are distinct evidence, neither implies
improved task performance.

Inputs: at most four recorded steps, `cameras.agentview` and `cameras.wrist`
contain 256×256 calibrated `rgb`, depth and world XYZ in metres, `calibration`;
`proprio` contains EEF position/quaternion and gripper positions. `masks` are
native SAM3 outputs from the *same step and camera*, resampled with nearest pixel
centres to the 256×256 grid. Raw high-resolution masks and alignment metadata
remain in the run; native segmentation returns are unchanged. Candidate code
has no controller, network, hidden object poses or official success signal.

## Container geometry example

`examples/manual-workbench/sensor_container_geometry.py` measures an approximately
horizontal container opening from 4–8 caller-selected inner-rim pixels. The
matching `container_candidate.json` contains its schema and exact source;
`container_metadata.json` records the originating Qwen timeout run. Publish with
the command above and these files, after replay validation.

Pixels use `[row, col]` in a calibrated image; `image_size` defaults to
`[1024, 1024]`. The tool samples the corresponding 256×256 world map. Within each
3×3 patch it retains neighbours within 2.5 cm of the selected pixel, requiring
at least three valid points. It reports excluded neighbours and depth spread.
It computes a convex hull and area centroid from measured rim XY points, plus
rim height and EEF offset. If rim heights disagree by more than 6 cm, it uses a
height group spanning at most 4 cm only when that group has at least four points
and 75% of all samples; excluded point indices remain visible in the result.
Otherwise it withholds the opening estimate. Reuse this result only while the container remains
stationary. A visible object-bottom pixel optionally yields a point's signed
height and alignment relative to the sampled opening.

The caller must identify the surfaces. This tool does not infer object identity,
the full opening boundary, object footprint, hidden floor, collision-free motion
or success. Occlusion can invalidate reused pixel locations even when the
container stays stationary. Poor or inconsistent samples return an explicit
status rather than a placement target. It never executes a controller.

Generated manual tools omit absent optional parameters before sandbox dispatch;
defaults are resolved by each tool, as in the research toolkit.

## Evidence and limitations

Each unique task directory includes `manifest.json` (frozen tools, profile,
source hashes), `code/`, `code.diff`, `prompts.json`, `tool-declarations.json`,
`events.jsonl`, `states.json`, recorded RGB/depth/calibration/masks, native video,
transcript and `outcome.json`. Binary journal inputs are stored by content hash.
Logs are flushed incrementally. Process restarts preserve history; unfinished
manual runs are marked `abnormal_exit`, not robot failure. No automatic retention
cleanup or uploading of runtime files is implemented.

Official environment success, model finish, release actions and unverified
stable placement are separate. `completed` describes termination, not success.
Outcomes distinguish abort, timeout, budget exhaustion, connection failure,
other error and abnormal exit. Old records without a field display “未记录”.
Only returned SDK events/thinking summaries are captured. Token totals are
provider/SDK counters; unavailable monetary costs are not invented. Console
connection warnings mark stale images; manual interruption is logged.
