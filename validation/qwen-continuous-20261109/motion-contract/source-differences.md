# 候选运行源码差异审计

候选：`/home/zwy/work/embodied_harness/validation/qwen-continuous-20261109/motion-contract-test-checkout`。
该隔离目录继承之前的验证工作树，Git HEAD 为
`7ab895c8287d6114b2ba1ebb8414a8af7b8839d0`；本轮实际代码包含未提交的已验证 M 修改，
不能仅用 HEAD 复现。`source-handoff.json` 冻结了 301 个运行源码/文本配置文件 hash。

与 live `/home/zwy/work/harnessvla` 的完整 Python 差异清单见
`source-differences.json`，范围为 `rpent/`、`robots/`、`examples/`、`tests/`，
排除字节码、macOS `._` 资源文件及非运行的 validation 脚本。
上述范围没有 live-only Python 文件；source-only 项均为测试。

| 差异 | 分类与本次影响 |
| --- | --- |
| `robots/libero/eef_control.py` | 已批准 M：新增 `translate_to` |
| `robots/libero/research/manual.py` | 已批准 M 的注册/选中引导；其余差异是格式 |
| `rpent/dashboard/workbench.py` | 已批准 M 的默认排除；其余差异是格式 |
| `robots/libero/research/codex_sdk.py` | 先前保留的 Python 3.10 timeout 兼容修改，`asyncio.timeout` 改为 `wait_for`；仅 legacy `models.py` 的 `kind=codex_sdk` 分支使用，Qwen API 不进入 |
| `robots/univtac/pilot/__init__.py`、`rpent/dashboard/server.py` | AST 完全等价的格式差异 |
| `pyproject.toml` | 先前增加的 `anthropic>=1.9,<2` 兼容约束；本轮未安装/重装依赖。两边使用同一既有 venv，实际 Anthropic 1.13.0、pydantic-ai-slim 2.53.0、harness 0.53.0 |
| `robots/flexiv/DIRECT_RDK.md`、`README.md` | 非 LIBERO 文档，不是本次模型输入 |
| `examples/manual-workbench/sensor_patch_batch.py` 和其 `candidate.json` | 之前的 T 示例/候选。运行不会隐式加载 examples；03 保持 C 的旧不可变 generated 版本和旧库，不选 T |
| 其他 examples | UniVTAC 格式差异，AST 等价 |
| tests 的不同/新增文件 | 之前验证工作树和本次 M 测试，不进入运行路径；逐项 hash/AST 类型已列出 |

机械核验：M 三文件的修改前版本与 live AST 相同；当前 API planner、dashboard CLI、
LIBERO 原工具、env client/server、robot_spec，以及 session/tools 全部 Python 文件
共 14 项与 live 字节一致。独立导入 API planner 后，legacy Codex 模块未进入
`sys.modules`。这些检查不创建模型或发送请求，证据见 `active-path-check.json`。

因此本次限定表述是：**当前 Qwen API 执行路径仅有批准的 M 干预**。
不宣称整个目录在字节或所有后端功能上只差 M。差异保留并解释，未为追求目录一致
覆盖 live 独立修改；也未把未选中的 T 源示例当作 03 的工具版本。

03 仍须验证实际冻结的 20 个旧工具版本、C 经验材料与此前 C 一致，并只加
`native:translate_to`（版本 `6711255f161f2c32649b31f6c2ff8055f5c8544bfbdca507ce66fa4daac280af`）
及其两句选中引导。实际启动时，activate 后显式把 `RPENT_REPO_ROOT` 和 `PYTHONPATH`
都设置到此隔离根，避免从 live 路径启动 env server。
