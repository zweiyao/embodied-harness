# Working on RPent

Follow [CONTRIBUTING.md](CONTRIBUTING.md) for development conventions, including
module ownership and interface contracts, and for testing and pull requests.
Use the implementation and its callers to verify behavior; report disagreements
with documentation instead of assuming either is correct.

## Project Git workflow

- After each coherent code or documentation change and its applicable validation,
  commit the relevant changes and push the current task branch without asking
  again. Update its existing open pull request, or create one if none exists.
- Describe the final behavior, actual validation results, and remaining gaps in
  the pull request. Do not merge automatically.
- Keep credentials, videos, raw observations, model weights, and unrelated files
  out of commits. Preserve independent changes and do not force-push.

## Repository map

- `rpent/planner/`, `rpent/session/`, and `rpent/prompt/`: planner adapters,
  execution sessions, and shared prompt construction.
- `rpent/tools/` and `rpent/memory/`: tool execution, observations, and memory.
- `rpent/robots/`: robot discovery, descriptors, shared runtime, and Env/VLA
  components. `robots/<robot>/` owns each concrete integration.
- `rpent/cli/`, `rpent/dashboard/`, and `rpent/evaluation/`: entry points,
  interactive execution, and run results.
- `tests/`: offline tests and integration checks; see [tests/README.md](tests/README.md).
- `docs/source-en/` and `docs/source-zh/`: paired user and developer documentation.

## Development principles

- Confirm the working branch and relevant upstream state before editing. Read
  the closest current implementation and both sides of changed interfaces.
  Preserve unrelated working-tree changes.
- Reuse existing configuration, registration, RPC, runtime, and artifact
  helpers. Prefer RLinf's supported Env/VLA implementations with thin RPent
  adapters.
- Base compatibility paths and new abstractions on actual consumers or
  supported data.
- Validate external inputs at the boundary that owns the operation. Keep
  internal control flow direct, avoid repeated checks of established state,
  and preserve useful errors. Make resource ownership and cleanup explicit.
- Keep optional simulator/model imports at their use sites so basic imports,
  robot discovery, and CLI help work without every robot extra installed.
- Follow neighboring code for naming and structure, use the project logger,
  and follow CONTRIBUTING's type annotation and docstring conventions.
- Write prose about current behavior and non-obvious constraints. Keep review
  exchanges and implementation history in PR discussions or migration notes.
  Translate meaning into natural Chinese and preserve technical identifiers.
- Keep prompts and tool descriptions focused on the model's task. Remove
  repetition without dropping required behavior or operational constraints.
- Test observable behavior and concrete regressions, reusing existing cases
  and fixtures where possible. Avoid tests that merely restate implementation
  details. Never weaken failing tests to make a change pass.

## Task skills

Read the relevant skill when the task calls for it; ordinary edits do not
require loading every skill.

| Task | Skill |
| --- | --- |
| Explain and review a PR, or review an explicitly selected local diff | [review-pr](.agents/skills/review-pr/SKILL.md) |
| Check documentation, comments, translations, or user/model-facing prose | [docs-check](.agents/skills/docs-check/SKILL.md) |
| Select and run checks for a change, or prepare validation evidence | [verify-change](.agents/skills/verify-change/SKILL.md) |
| Add a robot integration or extend its Env/VLA/tool/runtime wiring | [add-robot](.agents/skills/add-robot/SKILL.md) |

Reuse repository tools and the commands documented in CONTRIBUTING and the
test guide. Report what ran, its result, and what remains unverified; keep
integration evidence distinct from benchmark task success.

Skill sources live in `.agents/skills/`. `.claude/skills` links to that whole
directory, and `CLAUDE.md` links to this file. Edit the canonical files so both
clients share the same instructions. Keep each skill self-contained in its
`SKILL.md` and link to existing repository resources.

## 经验与 harness 修改审批

- 新增或修改经验前，先判断它是可迁移的通用经验，还是有明确适用条件的任务／任务族经验；只适用于一次摆放或一次轨迹的动作记录，不进入 agent 经验库。任务经验必须说明适用条件，不能作为所有任务的默认策略。
- 经验正文保留观察依据、判断方法、失效条件、来源实验 ID 和验证状态；不写入特定轨迹的固定坐标、正负方向、位移、角度、力值或动作序列，即使附有“仅供参考”也不保留。具体数值留在实验记录或独立复盘报告中，不能把单次成功或失败推广为通用规律。
- 坐标系、单位、参数格式等接口契约仍由工具说明提供；当前容差、设备参数和控制限制读取运行配置或接口反馈，不硬编码成经验。不得以清理经验为由删除控制保护或修改控制参数。
- 经验继续按 RPent 格式保存为独立文件并登记 MEMORY.md，按需加载；不把任务经验加入系统提示词。
- 新增、修改或删除经验，以及修改 harness 的提示词、工具说明、工具实现、观测／动作／记忆流程或实验行为配置之前，先向用户展示拟修改文件、具体前后内容（新文件给出草稿）、适用范围、依据及验证计划，取得针对该改动的明确同意后再修改或部署。可先只读分析；草稿不得接入运行环境。已有明确授权仅覆盖用户确认的范围，不能扩展为持续自动优化授权。
- 获准修改并验证后仍按项目要求自动提交、推送和更新 PR；提交或 PR 不替代修改前审批。完成时逐项告知实际改动和未验证部分。
