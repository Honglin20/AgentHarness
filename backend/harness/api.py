from __future__ import annotations

import asyncio
from typing import Any, Literal, Type

from pydantic import BaseModel

from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry


class Agent:
    """Declarative agent definition."""

    def __init__(
        self,
        name: str,
        after: list[str] | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        retries: int = 3,
        result_type: Type[BaseModel] | None = None,
    ):
        self.name = name
        self.after = after or []
        self.tools = tools
        self.model = model
        self.retries = retries
        self.result_type = result_type


class NodeTrace(BaseModel):
    agent_name: str
    status: Literal["success", "failed", "skipped"]
    duration_ms: int
    error: str | None = None


class WorkflowResult(BaseModel):
    outputs: dict[str, Any]
    errors: dict[str, str]
    trace: list[NodeTrace]


class Workflow:
    """Declarative workflow definition."""

    def __init__(
        self,
        name: str,
        agents: list[Agent],
        agents_dir: str = "agents",
        mcp_servers: list[McpServerConfig] | None = None,
        tool_registry: ToolRegistry | None = None,
    ):
        self.name = name
        self.agents = agents
        self.agents_dir = agents_dir
        self.mcp_servers = mcp_servers or []
        self.tool_registry = tool_registry or ToolRegistry()
        self._compiled = None
        self._mcp_bridges: list[McpBridge] = []

    def compile(self):
        """Compile the workflow into a LangGraph StateGraph.

        Uses whatever tools are currently in the ToolRegistry.
        Call await setup() first to connect MCP servers and register their tools.
        """
        from harness.engine.macro_graph import MacroGraphBuilder
        from harness.tools.defaults import default_tool_registry

        # Register self-built tools if registry is empty
        if not self.tool_registry.list_tools():
            self.tool_registry = default_tool_registry()

        builder = MacroGraphBuilder(tool_registry=self.tool_registry)
        graph = builder.build(self)
        self._compiled = graph.compile()
        return self._compiled

    async def setup(self):
        """Connect MCP servers and register their tools, then compile.

        This is the full setup: default self-built tools + MCP filesystem tools + compile.
        """
        from harness.tools.defaults import default_tool_registry, setup_default_mcp

        if not self.tool_registry.list_tools():
            self.tool_registry = default_tool_registry()

        # Connect default MCP servers
        bridges = await setup_default_mcp(self.tool_registry, workdir=self.agents_dir)

        # Connect user-provided MCP servers
        for config in self.mcp_servers:
            bridge = McpBridge(config, registry=self.tool_registry)
            await bridge.connect()
            await bridge.register_tools()
            bridges.append(bridge)

        self._mcp_bridges = bridges
        self.compile()

    async def arun(self, inputs: dict) -> WorkflowResult:
        """Run the workflow asynchronously. Primary execution path."""
        if self._compiled is None:
            self.compile()

        initial_state = {
            "inputs": inputs,
            "outputs": {},
            "errors": {},
            "metadata": {},
        }

        final_state = await self._compiled.ainvoke(initial_state)
        return self._build_result(final_state)

    def run(self, inputs: dict) -> WorkflowResult:
        """Run the workflow synchronously. Wraps arun() with asyncio.run()."""
        return asyncio.run(self.arun(inputs))

    def _build_result(self, final_state: dict) -> WorkflowResult:
        """Construct WorkflowResult from final LangGraph state."""
        outputs = final_state.get("outputs", {})
        errors = final_state.get("errors", {})
        metadata = final_state.get("metadata", {})

        trace = []
        for agent in self.agents:
            agent_meta = metadata.get(agent.name, {})
            duration_ms = agent_meta.get("duration_ms", 0) if isinstance(agent_meta, dict) else 0
            status = "failed" if agent.name in errors else "success"
            error_msg = errors.get(agent.name)

            trace.append(NodeTrace(
                agent_name=agent.name,
                status=status,
                duration_ms=duration_ms,
                error=error_msg,
            ))

        return WorkflowResult(outputs=outputs, errors=errors, trace=trace)

    async def cleanup(self):
        """Disconnect MCP servers."""
        for bridge in self._mcp_bridges:
            await bridge.disconnect()
        self._mcp_bridges = []
