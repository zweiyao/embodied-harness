Add a Planner
=============

A planner receives prompts, chooses tools, and consumes their results. To add one, subclass ``Planner``, implement ``solve``, and expose it through the construction path and CLI choices.

The following interface sketch omits model requests and the tool loop; it is not a runnable implementation. See ``rpent/planner/api_loop.py`` for a complete backend.

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
           # Call the model with system_prompt, user_message, and tools.
           # Execute each tool call through this interface:
           tool_result = toolkit.execute_tool(tool_name, arguments)
           ...
           return PlannerResult(
               finish_result=finish_result,
               messages=messages,
               stats=stats,
               error=error,
           )

Any planner must:

1. Accept the rendered ``system_prompt`` and ``user_message``.
2. Read each tool's ``name``, ``description``, and ``input_schema`` from
   ``toolkit.list_tools()`` and execute
   tools with ``toolkit.execute_tool(name, arguments)``.
3. Convert ``ToolResult.to_text()`` and PNG bytes in ``ToolResult.images`` to the
   format expected by the model SDK.
4. Detect ``ToolResult.data.get("_finish")`` and stop according to
   ``max_turns`` and any other limits.
5. Return a ``PlannerResult`` containing the finish state, messages,
   statistics, and an optional error.

Because the RPent tool schemas and prompt-rendering path stay the same,
adding a planner does not require changes to tools or environment
servers. See :doc:`architecture` for the interface, and
:doc:`add_primitive` if you want to expose new tools to
your custom planner.

Wire and Validate the Planner
-----------------------------

Add a construction branch in ``rpent/planner/base.py:build_planner`` and a CLI choice in ``rpent/cli/main.py``. If the planner supports Dashboard selection or connection diagnostics, wire those entry points and ``rpent/planner/check.py`` as well.

Verify tool dispatch, text and image results, ``finish``, turn limits, errors, and the interruption and interaction paths you support. Reuse test patterns in ``tests/unit_tests/rpent/planner/``. Validate real model connectivity separately.

Codex Instructions and Analysis Workspace
----------------------------------------------------------------------

The Codex adapter sends the fixed prompt as SDK ``developer_instructions``
and the task as the first user input. Follow-up messages stay in the same
thread without repeating the fixed instructions. Other planners retain their
existing system/user interfaces.

``--codex-analysis`` explicitly enables native command execution, Python
calculations and image inspection. It defaults to off. Model and reasoning
effort remain ordinary configuration: for example, ``--model gpt-6-astra
--reasoning-effort high``. The runner supplies ``analysis_enabled`` only for
Codex; selecting an API model does not grant Codex capabilities.

Each enabled run works in ``<output_dir>/agent/``. Its ``workspace.json``
identifies the Python interpreter, evidence and memory paths; ``NOTES.md``
and ``scratch/`` hold notes, scripts and crops. A Codex permission profile
grants writes to this workspace while keeping source, evidence and published
memory read-only. RPent file-tool writes use the same boundary. Native
analysis commands have no network access and cannot open a second controller
connection. Robot actions still go through the registered RPent MCP tools;
other MCP servers, applications, browsing and multi-agent tools stay disabled.

``prompts.json`` saves the submitted texts. ``prompt-sources.json`` records
the selected factories, loaded files, hashes and backend roles. The
``codex-capabilities.json`` manifest describes requested settings; inspect
SDK events and produced files to verify actual capabilities. A successful
calculation probe is not evidence of robot-task success.

On Linux, native execution requires working Bubblewrap and user namespaces.
Check this prerequisite on the deployment host before enabling analysis. A
sandbox startup failure leaves calculations and write protection unverified;
do not replace the permission profile with full access. See the
`Codex Linux sandbox requirements <https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md>`_.
