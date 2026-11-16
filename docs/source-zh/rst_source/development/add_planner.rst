添加规划器
===============

规划器负责接收提示词、选择工具并处理工具结果。接入自定义规划器时，继承 ``Planner`` 并实现 ``solve``，然后将其加入构建入口和 CLI 选项。

以下为接口示意，省略了模型请求和工具循环，不能直接作为实现运行。完整示例可参考 ``rpent/planner/api_loop.py``。

.. code-block:: python

   # rpent/planner/my_planner.py
   from rpent.planner.base import Planner, PlannerResult

   class MyPlanner(Planner):
       def solve(
           self,
           *,
           system_prompt,
           user_message,
           toolkit,
           max_turns,
           input_queue=None,
           dashboard_interaction=None,
       ):
           tools = toolkit.list_tools()
           # 使用 system_prompt、user_message 和 tools 调用模型。
           # 每次工具调用都通过下面的接口执行：
           tool_result = toolkit.execute_tool(tool_name, arguments)
           ...
           return PlannerResult(
               finish_result=finish_result,
               messages=messages,
               stats=stats,
               error=error,
           )

任何 planner 必须：

1. 接收已经渲染好的 ``system_prompt`` 和 ``user_message``。
2. 从 ``toolkit.list_tools()`` 取得工具的 ``name``、``description`` 和 ``input_schema``，并通过 ``toolkit.execute_tool(name, arguments)`` 执行工具。
3. 将 ``ToolResult.to_text()`` 的文本和 ``ToolResult.images`` 中的 PNG 字节转换成模型 SDK 所需的格式。
4. 识别 ``ToolResult.data.get("_finish")``，并按 ``max_turns`` 等限制终止循环。
5. 返回包含结束状态、消息、统计信息和可选错误的 ``PlannerResult``。

由于 RPent 工具定义和 prompt 渲染流程保持不变，新增 planner 不需要修改工具或环境服务。接口参见 :doc:`architecture`；想给
自定义 planner 暴露新工具，见 :doc:`add_primitive`。

接入与验证
---------------

在 ``rpent/planner/base.py`` 的 ``build_planner`` 中添加构建分支，并在 ``rpent/cli/main.py`` 的 ``--planner`` 选项中加入名称。需要 Dashboard 或连接诊断时，还应接入对应的规划器选择与 ``rpent/planner/check.py``，不能仅添加一个类。

验证工具调用、文本和图像返回、``finish``、轮数上限、错误结果，以及需要支持的中断和交互路径。复用 ``tests/unit_tests/rpent/planner/`` 中的测试模式；真实模型连接需要单独验证。

Codex 指令与分析目录
----------------------------------------------------------------------

Codex 适配器通过 SDK 的 ``developer_instructions`` 传入固定提示词，
首次用户输入只包含任务。后续消息保留在同一线程中，不重复注入固定指令。
其他规划器继续使用原有的 system/user 接口。

``--codex-analysis`` 显式开启原生命令执行、Python 计算和图片检查，默认关闭。
模型和推理强度仍由常规配置指定，例如 ``--model gpt-6-astra
--reasoning-effort high``。运行器仅对 Codex 提供 ``analysis_enabled``；
选择 API 模型不会获得 Codex 原生能力。

开启后，每轮工作目录为 ``<output_dir>/agent/``。其中 ``workspace.json``
提供 Python 解释器、证据及经验路径；``NOTES.md`` 和 ``scratch/`` 用于笔记、
脚本和裁图。默认 Codex 权限配置只允许写入该目录，源码、原始证据和发布经验保持只读；
RPent 文件工具也使用相同的写入边界。原生分析命令没有网络访问权限，不能另建
控制器连接。机器人动作仍经过已登记的 RPent MCP 工具；其他 MCP、外部应用、
浏览和多 agent 工具保持关闭。

``prompts.json`` 保存实际提交的文本；``prompt-sources.json`` 记录所选工厂、
加载文件、哈希和后端消息角色。``codex-capabilities.json`` 仅说明请求的配置，
实际能力需要通过 SDK 事件及生成文件验证。计算探针通过不代表机器人任务成功。

默认受限模式在 Linux 上执行原生命令，需要可用的 Bubblewrap 和用户命名空间。启用分析前，
先在部署主机验证这一前置条件；沙箱启动失败时，计算和写入保护均未得到验证，
不能自动改用全权限来代替。参见
`Codex Linux 沙箱要求 <https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md>`_。

显式全权限模式
~~~~~~~~~~~~~~

``--codex-analysis --codex-full-access`` 为原生命令开启完整文件系统和网络访问，
审批策略为 ``never``。这由操作员显式选择，不会在沙箱报错时自动启用。
线程和后续交互都使用全权限，能力清单记录实际选择的模式。

机器人控制仍使用选定的 RPent 工具，RPent 文件工具仍只允许写入 ``agent/``。
此时源码、原始证据和发布经验的只读要求属于任务规则，不是操作系统隔离。
API 规划器不会因这些开关获得 Codex 原生能力。
