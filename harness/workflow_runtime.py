"""Workflow runtime — run/arun, MCP setup/cleanup, result assembly.

Free functions; the ``Workflow`` class methods are thin wrappers. Lifted
from ``harness/api.py`` for readability.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.tools.defaults import default_tool_registry, setup_default_mcp
from harness.tools.mcp_bridge import McpBridge
from harness.types import NodeTrace, TokenUsage, WorkflowResult

if TYPE_CHECKING:
    from harness.workflow import Workflow

logger = logging.getLogger(__name__)


def run_workflow(
    workflow: "Workflow",
    inputs: dict,
    ui: bool = False,
    work_dir: str | None = None,
) -> WorkflowResult:
    """Run the workflow. Primary API — synchronous, simple.

    Args:
        workflow: the workflow to run.
        inputs: Task input dict.
        ui: If True, auto-start server + open browser to visualize execution.
        work_dir: Working directory for agent file access and bash cwd.
            Defaults to ``os.getcwd()``. Use ``"/"`` for full filesystem access.
    """
    if ui:
        _launch_workflow_ui(workflow, inputs)
    return asyncio.run(_execute_workflow(workflow, inputs, work_dir=work_dir))


def _launch_workflow_ui(workflow: "Workflow", inputs: dict) -> None:
    """Start backend server and open browser for UI visualization."""
    import time
    import threading

    port = int(os.environ.get("HARNESS_PORT", "8000"))

    def _start_server():
        import uvicorn
        uvicorn.run("server.app:app", host="0.0.0.0", port=port, log_level="warning")

    # Check if server is already running
    import urllib.request
    try:
        urllib.request.urlopen(f"http://localhost:{port}/health", timeout=1)
    except Exception:
        t = threading.Thread(target=_start_server, daemon=True)
        t.start()
        time.sleep(2)

    # Create workflow via API so frontend can connect
    import urllib.request as ur
    data = json.dumps({
        "name": workflow.name,
        "agents": [a.to_dict() for a in workflow.agents],
        "inputs": inputs,
    }).encode()
    req = ur.Request(f"http://localhost:{port}/api/workflows", data=data,
                     headers={"Content-Type": "application/json"})
    resp = ur.urlopen(req)
    result = json.loads(resp.read())
    wid = result["workflow_id"]

    webbrowser.open(f"http://localhost:{port}?workflow={wid}")


async def arun_workflow(
    workflow: "Workflow",
    inputs: dict | None = None,
    config: dict | None = None,
    resume_value: Any | None = None,
) -> WorkflowResult:
    """Run the workflow asynchronously. For callers already in an async context.

    Caller is responsible for MCP lifecycle (call setup/cleanup if needed).

    Args:
        workflow: the workflow to run.
        inputs: Task input dict. None when resuming.
        config: LangGraph run config. If checkpointer is set and no config
            provided, uses ``{'configurable': {'thread_id': workflow.name}}``.
        resume_value: Value to pass to LangGraph interrupt() on resume.
            When provided, uses Command(resume=resume_value) instead of
            initial_state to resume from an interrupted checkpoint.
    """
    if workflow.mcp_servers and not workflow._mcp_setup_done:
        raise RuntimeError(
            "MCP servers are configured but setup() was not called. "
            "Call await workflow.setup() before arun(), or use run() instead."
        )

    if workflow._compiled is None:
        workflow.compile()

    if config is None and workflow.checkpointer is not None:
        config = {"configurable": {"thread_id": workflow.name}}

    if resume_value is not None:
        from langgraph.types import Command
        final_state = await workflow._compiled.ainvoke(
            Command(resume=resume_value), config=config,
        )
    else:
        initial_state = {
            STATE_INPUTS: inputs or {},
            STATE_OUTPUTS: {},
            STATE_ERRORS: {},
            STATE_METADATA: {},
        }
        final_state = await workflow._compiled.ainvoke(initial_state, config=config)

    result = _build_workflow_result(workflow, final_state)

    # Detect LangGraph interrupt: ainvoke returns {__interrupt__: [Interrupt(...)]}
    if isinstance(final_state, dict) and "__interrupt__" in final_state:
        interrupts = final_state["__interrupt__"]
        result.interrupted = True
        result.interrupt_value = interrupts[0].value if interrupts else None

    return result


async def setup_workflow(workflow: "Workflow", work_dir: str | None = None) -> None:
    """Connect MCP servers and register their tools, then compile.

    For advanced usage with ``arun()``. Not needed if using ``run()``.

    Args:
        workflow: the workflow to set up.
        work_dir: Working directory for MCP filesystem access.
            Defaults to ``os.getcwd()``. Use ``"/"`` for full filesystem access.
    """
    if not workflow.tool_registry.list_tools():
        workflow.tool_registry = default_tool_registry(event_bus=workflow._event_bus)

    mcp_workdir = work_dir or os.getcwd()
    bridges: list[McpBridge] = []
    if workflow.enable_filesystem_mcp:
        try:
            bridges = await setup_default_mcp(workflow.tool_registry, workdir=mcp_workdir)
        except Exception as e:
            import sys
            print(
                f"\n⚠  MCP filesystem server failed to start: {e}\n"
                f"   Install it with:\n"
                f"     npm install -g @modelcontextprotocol/server-filesystem\n"
                f"   Or skip MCP tools — bash, sub_agent work without it.\n",
                file=sys.stderr,
            )

    # Default-on: codegraph MCP. Provides codegraph_search / codegraph_context /
    # codegraph_callers / codegraph_callees / codegraph_impact / codegraph_node /
    # codegraph_explore / codegraph_status / codegraph_files / codegraph_trace
    # for code-aware agents. Soft-failure — workflow still runs without it.
    if workflow.enable_codegraph_mcp:
        try:
            from harness.tools.defaults import setup_codegraph_mcp
            cg_bridge = await setup_codegraph_mcp(
                workflow.tool_registry,
                path=workflow.codegraph_path,
            )
            if cg_bridge is not None:
                bridges.append(cg_bridge)
        except Exception as e:
            import sys
            print(
                f"\n⚠  codegraph MCP server failed to start: {e}\n"
                f"   Install it with:\n"
                f"     npm install -g @colbymchenry/codegraph\n"
                f"   Then in the project root: codegraph init -i\n"
                f"   Agents can still use bash to call `codegraph` directly.\n",
                file=sys.stderr,
            )

    for config in workflow.mcp_servers:
        try:
            bridge = McpBridge(config, registry=workflow.tool_registry, source="mcp_custom")
            await bridge.connect()
            await bridge.register_tools()
            bridges.append(bridge)
        except Exception as e:
            import sys
            print(
                f"\n⚠  Custom MCP server '{config.name}' failed: {e}\n"
                f"   Check the server is installed and the command is correct.\n",
                file=sys.stderr,
            )

    workflow._mcp_bridges = bridges
    workflow._mcp_setup_done = True
    workflow.compile()


async def cleanup_workflow(workflow: "Workflow") -> None:
    """Disconnect MCP servers. Best-effort — never raises."""
    for bridge in workflow._mcp_bridges:
        try:
            await bridge.disconnect()
        except BaseException:
            logger.exception("MCP bridge disconnect failed — process may leak")
    workflow._mcp_bridges = []
    workflow._mcp_setup_done = False


async def _execute_workflow(
    workflow: "Workflow",
    inputs: dict,
    work_dir: str | None = None,
) -> WorkflowResult:
    """Internal: full lifecycle in one event loop.

    LangGraph's ainvoke() is auto-traced by LangSmith when
    ``LANGCHAIN_TRACING_V2=true``, forming the top-level trace.
    """
    if work_dir is not None:
        p = Path(work_dir).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Work directory does not exist: {work_dir}")
        if not p.is_dir():
            raise NotADirectoryError(f"Work path is not a directory: {work_dir}")
    await setup_workflow(workflow, work_dir=work_dir)
    try:
        result = await arun_workflow(workflow, inputs)
    finally:
        await cleanup_workflow(workflow)
    return result


def _build_workflow_result(workflow: "Workflow", final_state: dict) -> WorkflowResult:
    """Construct ``WorkflowResult`` from final LangGraph state."""
    outputs = final_state.get(STATE_OUTPUTS, {})
    errors = final_state.get(STATE_ERRORS, {})
    metadata = final_state.get(STATE_METADATA, {})

    trace = []
    for agent in workflow.agents:
        agent_meta = metadata.get(agent.name, {})
        duration_ms = agent_meta.get("duration_ms", 0) if isinstance(agent_meta, dict) else 0

        token_usage = None
        tu = agent_meta.get("token_usage") if isinstance(agent_meta, dict) else None
        if isinstance(tu, dict):
            token_usage = TokenUsage(**tu)

        if agent.name in errors:
            status = "failed"
        elif agent.name in outputs:
            status = "success"
        else:
            status = "skipped"

        trace.append(NodeTrace(
            agent_name=agent.name,
            status=status,
            duration_ms=duration_ms,
            error=errors.get(agent.name),
            token_usage=token_usage,
        ))

    return WorkflowResult(outputs=outputs, errors=errors, trace=trace)
