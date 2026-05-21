from __future__ import annotations

import asyncio
import json
import os
import webbrowser
from pathlib import Path
from typing import Any, Literal, Type

from pydantic import BaseModel

from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.tools.defaults import default_tool_registry, setup_default_mcp
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry

# Directories resolved from this file's location — not cwd-dependent
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_WORKFLOWS_DIR = _BACKEND_DIR.parent / "workflows"
_DEFAULT_AGENTS_DIR = str(_BACKEND_DIR / "agents")


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
        on_pass: str | None = None,
        on_fail: str | None = None,
    ):
        self.name = name
        self.after = after or []
        self.tools = tools
        self.model = model
        self.retries = retries
        self.result_type = result_type
        self.on_pass = on_pass
        self.on_fail = on_fail

    @property
    def has_conditional_edges(self) -> bool:
        return self.on_pass is not None or self.on_fail is not None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "after": self.after,
            "tools": self.tools,
            "model": self.model,
            "retries": self.retries,
        }
        if self.on_pass is not None:
            d["on_pass"] = self.on_pass
        if self.on_fail is not None:
            d["on_fail"] = self.on_fail
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Agent:
        return cls(
            name=d["name"],
            after=d.get("after", []),
            tools=d.get("tools"),
            model=d.get("model"),
            retries=d.get("retries", 3),
            on_pass=d.get("on_pass"),
            on_fail=d.get("on_fail"),
        )


class TokenUsage(BaseModel):
    input: int
    output: int
    total: int


class NodeTrace(BaseModel):
    agent_name: str
    status: Literal["success", "failed", "skipped"]
    duration_ms: int
    error: str | None = None
    token_usage: TokenUsage | None = None


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
        agents_dir: str = _DEFAULT_AGENTS_DIR,
        mcp_servers: list[McpServerConfig] | None = None,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,
        max_iterations: int = 3,
    ):
        self.name = name
        self.agents = agents
        self.agents_dir = agents_dir
        self.mcp_servers = mcp_servers or []
        self.tool_registry = tool_registry or ToolRegistry()
        self._event_bus = event_bus
        self.max_iterations = max_iterations
        self._compiled = None
        self._builder: Any | None = None  # MacroGraphBuilder, set by compile()
        self._mcp_setup_done = False
        self._mcp_bridges: list[McpBridge] = []

    def compile(self):
        """Compile the workflow into a LangGraph StateGraph.

        Uses whatever tools are currently in the ToolRegistry.
        If registry is empty, registers default self-built tools (sub_agent + bash).
        Does NOT connect MCP servers — call run() for full setup.
        """
        from harness.engine.macro_graph import MacroGraphBuilder

        if not self.tool_registry.list_tools():
            self.tool_registry = default_tool_registry()

        builder = MacroGraphBuilder(
            tool_registry=self.tool_registry,
            event_bus=self._event_bus,
            max_iterations=self.max_iterations,
        )
        graph = builder.build(self)
        self._builder = builder
        self._compiled = graph.compile()
        return self._compiled

    def save(self) -> Path:
        """Save workflow definition to workflows/<name>.json."""
        _WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        path = _WORKFLOWS_DIR / f"{self.name}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return path

    @classmethod
    def load(cls, name: str, agents_dir: str = _DEFAULT_AGENTS_DIR) -> Workflow:
        """Load a saved workflow definition from workflows/<name>.json."""
        path = _WORKFLOWS_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Workflow '{name}' not found at {path}")
        data = json.loads(path.read_text())
        return cls.from_dict(data, agents_dir=agents_dir)

    @staticmethod
    def list_saved() -> list[dict]:
        """List all saved workflow definitions with their DAG structure."""
        if not _WORKFLOWS_DIR.exists():
            return []
        from harness.compiler.dag_builder import build_dag

        result = []
        for f in sorted(_WORKFLOWS_DIR.glob("*.json")):
            data = json.loads(f.read_text())
            agents = [Agent.from_dict(a) for a in data.get("agents", [])]
            node_order = build_dag(agents)
            edges = []
            for a in agents:
                for dep in a.after:
                    edges.append([dep, a.name])
            result.append({
                "name": data["name"],
                "agents": [a.to_dict() for a in agents],
                "dag": {"nodes": node_order, "edges": edges},
            })
        return result

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "agents": [a.to_dict() for a in self.agents],
        }

    @classmethod
    def from_dict(cls, data: dict, agents_dir: str = _DEFAULT_AGENTS_DIR) -> Workflow:
        agents = [Agent.from_dict(a) for a in data.get("agents", [])]
        return cls(name=data["name"], agents=agents, agents_dir=agents_dir)

    def run(self, inputs: dict, ui: bool = False) -> WorkflowResult:
        """Run the workflow. Primary API — synchronous, simple.

        Args:
            inputs: Task input dict.
            ui: If True, auto-start server + open browser to visualize execution.
        """
        if ui:
            self._launch_ui(inputs)
        return asyncio.run(self._execute(inputs))

    def _launch_ui(self, inputs: dict) -> None:
        """Start backend server and open browser for UI visualization."""
        import subprocess
        import time
        import threading

        backend_dir = Path(__file__).resolve().parent.parent

        def _start_server():
            import uvicorn
            uvicorn.run("server.app:app", host="0.0.0.0", port=8001, log_level="warning")

        # Check if server is already running
        import urllib.request
        try:
            urllib.request.urlopen("http://localhost:8001/health", timeout=1)
        except Exception:
            t = threading.Thread(target=_start_server, daemon=True)
            t.start()
            time.sleep(2)

        # Create workflow via API so frontend can connect
        import urllib.request as ur
        data = json.dumps({
            "name": self.name,
            "agents": [a.to_dict() for a in self.agents],
            "inputs": inputs,
        }).encode()
        req = ur.Request("http://localhost:8001/api/workflows", data=data,
                         headers={"Content-Type": "application/json"})
        resp = ur.urlopen(req)
        result = json.loads(resp.read())
        wid = result["workflow_id"]

        # Open browser
        webbrowser.open(f"http://localhost:3000?workflow={wid}")

    async def arun(self, inputs: dict) -> WorkflowResult:
        """Run the workflow asynchronously. For callers already in an async context.

        Caller is responsible for MCP lifecycle (call setup/cleanup if needed).
        """
        if self.mcp_servers and not self._mcp_setup_done:
            raise RuntimeError(
                "MCP servers are configured but setup() was not called. "
                "Call await workflow.setup() before arun(), or use run() instead."
            )

        if self._compiled is None:
            self.compile()

        initial_state = {
            STATE_INPUTS: inputs,
            STATE_OUTPUTS: {},
            STATE_ERRORS: {},
            STATE_METADATA: {},
        }

        final_state = await self._compiled.ainvoke(initial_state)
        return self._build_result(final_state)

    async def setup(self):
        """Connect MCP servers and register their tools, then compile.

        For advanced usage with arun(). Not needed if using run().
        """
        if not self.tool_registry.list_tools():
            self.tool_registry = default_tool_registry()

        bridges: list[McpBridge] = []
        try:
            bridges = await setup_default_mcp(self.tool_registry, workdir=self.agents_dir)
        except Exception as e:
            import sys
            print(
                f"\n⚠  MCP filesystem server failed to start: {e}\n"
                f"   Install it with:\n"
                f"     npm install -g @modelcontextprotocol/server-filesystem\n"
                f"   Or skip MCP tools — bash, sub_agent work without it.\n",
                file=sys.stderr,
            )

        for config in self.mcp_servers:
            try:
                bridge = McpBridge(config, registry=self.tool_registry)
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

        self._mcp_bridges = bridges
        self._mcp_setup_done = True
        self.compile()

    async def cleanup(self):
        """Disconnect MCP servers. Best-effort — never raises."""
        for bridge in self._mcp_bridges:
            try:
                await bridge.disconnect()
            except BaseException:
                pass
        self._mcp_bridges = []
        self._mcp_setup_done = False

    async def _execute(self, inputs: dict) -> WorkflowResult:
        """Internal: full lifecycle in one event loop.

        LangGraph's ainvoke() is auto-traced by LangSmith when
        LANGCHAIN_TRACING_V2=true, forming the top-level trace.
        """
        await self.setup()
        try:
            result = await self.arun(inputs)
        finally:
            await self.cleanup()
        return result

    def _build_result(self, final_state: dict) -> WorkflowResult:
        """Construct WorkflowResult from final LangGraph state."""
        outputs = final_state.get(STATE_OUTPUTS, {})
        errors = final_state.get(STATE_ERRORS, {})
        metadata = final_state.get(STATE_METADATA, {})

        trace = []
        for agent in self.agents:
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
