from __future__ import annotations

import asyncio
import json
import os
import webbrowser
from pathlib import Path
from typing import Any, Literal, Type

from pydantic import BaseModel, Field

from harness.compiler.md_parser import resolve_agent_md
from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.tools.defaults import default_tool_registry, setup_default_mcp
from harness.tools.mcp_bridge import McpBridge, McpServerConfig
from harness.tools.registry import ToolRegistry

from harness.paths import get_project_root

_BACKEND_DIR = get_project_root()
_WORKFLOWS_DIR = _BACKEND_DIR / "workflows"
_BENCHMARKS_DIR = _BACKEND_DIR / "benchmarks"
_DEFAULT_AGENTS_DIR = str(_BACKEND_DIR / "agents")


def _extract_description(agent_name: str, workflow_dir: Path) -> str:
    """Extract the first non-heading, non-empty line from an agent.md as description."""
    try:
        path = resolve_agent_md(agent_name, workflow_dir)
        content = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    in_frontmatter = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


class AgentResult(BaseModel):
    """Default result_type. Conclusion goes in summary, reasoning goes in details."""
    summary: str = Field(description="Your final conclusion or answer. Be concise and direct.")
    details: str | None = Field(default=None, description="Your reasoning process, analysis steps, and key observations. Show your chain of thought here.")


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
        eval: bool = False,
        eval_target: str | None = None,
    ):
        self.name = name
        # None 表示仅通过条件边触发，不作为入口节点
        # [] 表示入口节点（从 START 开始）
        # [...] 表示有静态依赖
        if after is None:
            self.after = None
        else:
            self.after = after  # 保持原值，包括 []
        self.tools = tools
        self.model = model
        self.retries = retries
        self.result_type = result_type if result_type is not None else AgentResult
        self.on_pass = on_pass
        self.on_fail = on_fail
        self.eval = eval
        # eval_target: set on materialized judge agents; survives save/load so
        # the engine can route them through _make_judge_node_func after reload.
        # Stored as a public attr (also assigned to the legacy _eval_target
        # alias for back-compat with code that still reads the private form).
        self.eval_target = eval_target
        if eval_target is not None:
            self._eval_target = eval_target

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
        if self.eval:
            d["eval"] = True
        if self.eval_target is not None:
            d["eval_target"] = self.eval_target
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Agent:
        return cls(
            name=d["name"],
            after=d.get("after"),
            tools=d.get("tools"),
            model=d.get("model"),
            retries=d.get("retries", 3),
            on_pass=d.get("on_pass"),
            on_fail=d.get("on_fail"),
            eval=bool(d.get("eval", False)),
            eval_target=d.get("eval_target"),
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
    interrupted: bool = False
    interrupt_value: Any | None = None


class Workflow:
    """Declarative workflow definition."""

    def __init__(
        self,
        name: str,
        agents: list[Agent],
        workflow_dir: Path | None = None,
        agents_dir: str | None = None,  # legacy back-compat — derived from workflow_dir if omitted
        mcp_servers: list[McpServerConfig] | None = None,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,
        max_iterations: int = 3,
        checkpointer: Any | None = None,
        envelope: dict[str, int] | None = None,
        enable_filesystem_mcp: bool = True,
        enable_codegraph_mcp: bool = True,
        codegraph_path: str | None = None,
    ):
        self.name = name
        self.agents = agents
        # New: workflow_dir is the canonical per-workflow directory.
        # If a legacy agents_dir is passed (and no workflow_dir), keep it for MCP
        # workdir back-compat — its parent doubles as workflow_dir.
        if workflow_dir is not None:
            self.workflow_dir = Path(workflow_dir)
        elif agents_dir is not None:
            # Legacy: treat the directory containing the agents folder as the workflow_dir.
            # If agents_dir already points at a directory called "agents", use its parent;
            # otherwise treat agents_dir itself as the workflow_dir (some old callers passed
            # a flat directory of MDs).
            ad = Path(agents_dir)
            self.workflow_dir = ad.parent if ad.name == "agents" else ad
        else:
            self.workflow_dir = _WORKFLOWS_DIR / name
        self._legacy_agents_dir = agents_dir  # preserved if caller passed it
        self.mcp_servers = mcp_servers or []
        self.tool_registry = tool_registry or ToolRegistry()
        self._event_bus = event_bus
        self.max_iterations = max_iterations
        self.checkpointer = checkpointer
        self.envelope = envelope
        self.enable_filesystem_mcp = enable_filesystem_mcp
        self.enable_codegraph_mcp = enable_codegraph_mcp
        self.codegraph_path = codegraph_path
        self._compiled = None
        self._builder: Any | None = None  # MacroGraphBuilder, set by compile()
        self._mcp_setup_done = False
        self._mcp_bridges: list[McpBridge] = []

    @property
    def agents_dir(self) -> str:
        """Legacy alias — directory holding agent MD files.

        Returns the explicit legacy value if one was passed, else
        ``str(self.workflow_dir / 'agents')`` under the new layout.
        """
        if self._legacy_agents_dir is not None:
            return self._legacy_agents_dir
        return str(self.workflow_dir / "agents")


    def compile(self):
        """Compile the workflow into a LangGraph StateGraph.

        Uses whatever tools are currently in the ToolRegistry.
        If registry is empty, registers default self-built tools (sub_agent + bash).
        Does NOT connect MCP servers — call run() for full setup.

        Also runs the two-phase GraphMutator pipeline:

          1. ``mutator.mutate(workflow)``  — in-memory DAG rewrite
          2. ``mutator.persist(workflow)`` — durable side files (e.g. judge MD)
          3. clear ``eval=True`` on every agent — materialization is one-shot

        After compile() returns, ``save()`` can persist a workflow.json that
        reflects the materialized DAG with no ``eval`` flags remaining.
        """
        from harness.engine.macro_graph import MacroGraphBuilder

        if not self.tool_registry.list_tools():
            self.tool_registry = default_tool_registry(event_bus=self._event_bus)

        # Auto-register built-in Hook plugins (idempotent)
        if self._event_bus is not None:
            from harness.extensions.plugins import register_default_hooks
            register_default_hooks(self._event_bus)

        # Two-phase mutator pipeline: mutate (in-memory) then persist (side files).
        # Persist failures (e.g. summarizer LLM error) propagate — compile aborts.
        if self._event_bus is not None and hasattr(self._event_bus, "get_mutators"):
            for mutator in self._event_bus.get_mutators():
                mutator.mutate(self)
                mutator.persist(self)

        # Any remaining eval=True means no mutator claimed it (e.g. user forgot
        # to .use(EvalJudge())). Fail loud rather than silently strip the flag.
        unhandled = [a.name for a in self.agents if getattr(a, "eval", False)]
        if unhandled:
            from harness.extensions.eval.errors import EvalCompileError
            raise EvalCompileError(
                f"Agents {unhandled} have eval=True but no GraphMutator handled them. "
                f"Call workflow.use(EvalJudge()) before compile()."
            )

        builder = MacroGraphBuilder(
            tool_registry=self.tool_registry,
            event_bus=self._event_bus,
            max_iterations=self.max_iterations,
            envelope=self.envelope,
        )
        graph = builder.build(self)
        self._builder = builder
        compile_kwargs = {}
        if self.checkpointer is not None:
            compile_kwargs["checkpointer"] = self.checkpointer
        self._compiled = graph.compile(**compile_kwargs)
        return self._compiled

    def use(self, extension) -> "Workflow":
        """Register an extension (Hook / Middleware / GraphMutator) on this
        workflow's event bus.

        If no bus was provided at construction time, a local Bus is created
        and reused for subsequent extensions on this workflow.

        Returns self for fluent chaining:

            wf = (
                Workflow("research", agents=[...])
                .use(AutoCompact(threshold_tokens=8000))
                .use(FileMemory(path="./memory.md"))
            )
        """
        if self._event_bus is None:
            from harness.extensions.bus import Bus
            self._event_bus = Bus()
        if not hasattr(self._event_bus, "register"):
            raise TypeError(
                "Workflow.event_bus does not support extensions. "
                "Pass a harness.extensions.bus.Bus instance instead of a "
                "custom event bus, or omit it to create one automatically."
            )
        self._event_bus.register(extension)
        return self

    def save(self) -> Path:
        """Save workflow definition to workflows/<name>/workflow.json.

        Creates the per-workflow directory plus its ``agents/`` and ``scripts/``
        subdirectories if they don't exist.

        Strict: if any agent still has ``eval=True``, raises
        ``EvalNotCompiledError``. Call ``compile()`` first so EvalJudge
        materializes the judge nodes into the DAG.
        """
        from harness.extensions.eval.errors import EvalNotCompiledError

        uncompiled = [a.name for a in self.agents if getattr(a, "eval", False)]
        if uncompiled:
            raise EvalNotCompiledError(
                f"Cannot save workflow '{self.name}': agents {uncompiled} have eval=True "
                f"but compile() has not run. Call workflow.compile() before save() so "
                f"EvalJudge can materialize judge nodes into workflow.json."
            )

        self.workflow_dir.mkdir(parents=True, exist_ok=True)
        (self.workflow_dir / "agents").mkdir(exist_ok=True)
        (self.workflow_dir / "scripts").mkdir(exist_ok=True)
        path = self.workflow_dir / "workflow.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        print(f"[Workflow] saved → {path.resolve()}")
        return path

    @classmethod
    def load(cls, name: str, agents_dir: str | None = None) -> Workflow:
        """Load a saved workflow definition from workflows/<name>/workflow.json.

        Resolution order:
          1. Registry (builtin + project + extra registrations)
          2. Legacy _WORKFLOWS_DIR fallback

        ``agents_dir`` is retained for back-compat; new layout derives it from
        ``workflows/<name>/agents``.
        """
        from harness.registry import get_registry
        try:
            meta = get_registry().resolve_workflow(name)
            wf_dir = meta.resource_dir
        except FileNotFoundError:
            wf_dir = _WORKFLOWS_DIR / name

        path = wf_dir / "workflow.json"
        if not path.exists():
            raise FileNotFoundError(f"Workflow '{name}' not found at {path}")
        data = json.loads(path.read_text())
        return cls.from_dict(data, workflow_dir=wf_dir, agents_dir=agents_dir)

    @staticmethod
    def list_saved(user_id: str | None = None) -> list[dict]:
        """List all saved workflow definitions with their DAG structure.

        Returns:
            - Shared workflows (from workflows/_shared/workflows/) - always returned
            - Private workflows for the given user (from workflows/users/{user_id}/workflows/) - if user_id provided
            - Legacy workflows (from workflows/ root) - only for default user or when no user_id

        Args:
            user_id: User ID for filtering private workflows.
                     - None or "default": returns shared + legacy (backward compatibility)
                     - Other values: returns shared + user's private (legacy hidden)
        """
        from harness.compiler.dag_builder import build_dag

        result = []

        # 1. Shared workflows
        shared_root = _WORKFLOWS_DIR / "_shared" / "workflows"
        if shared_root.exists():
            for f in sorted(shared_root.glob("*/workflow.json")):
                data = json.loads(f.read_text())
                agents = [Agent.from_dict(a) for a in data.get("agents", [])]
                node_order = build_dag(agents)
                edges = []
                conditional_edges = []
                for a in agents:
                    for dep in a.after or []:
                        edges.append([dep, a.name])
                    if a.on_pass is not None:
                        conditional_edges.append({"from": a.name, "to": a.on_pass, "label": "pass"})
                    if a.on_fail is not None:
                        conditional_edges.append({"from": a.name, "to": a.on_fail, "label": "fail"})
                agent_dicts = [a.to_dict() for a in agents]
                for ad in agent_dicts:
                    ad["description"] = _extract_description(ad["name"], f.parent)
                result.append({
                    "name": data["name"],
                    "agents": agent_dicts,
                    "dag": {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
                    "workflow_dir": str(f.parent),
                    "scope": "shared",
                })

        # 2. Private workflows (if user_id provided)
        if user_id:
            private_root = _WORKFLOWS_DIR / "users" / user_id / "workflows"
            if private_root.exists():
                for f in sorted(private_root.glob("*/workflow.json")):
                    data = json.loads(f.read_text())
                    agents = [Agent.from_dict(a) for a in data.get("agents", [])]
                    node_order = build_dag(agents)
                    edges = []
                    conditional_edges = []
                    for a in agents:
                        for dep in a.after or []:
                            edges.append([dep, a.name])
                        if a.on_pass is not None:
                            conditional_edges.append({"from": a.name, "to": a.on_pass, "label": "pass"})
                        if a.on_fail is not None:
                            conditional_edges.append({"from": a.name, "to": a.on_fail, "label": "fail"})
                    agent_dicts = [a.to_dict() for a in agents]
                    for ad in agent_dicts:
                        ad["description"] = _extract_description(ad["name"], f.parent)
                    result.append({
                        "name": data["name"],
                        "agents": agent_dicts,
                        "dag": {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
                        "workflow_dir": str(f.parent),
                        "scope": "private",
                    })

        # 3. Legacy workflows (backward compatibility when no user_id or for default user)
        if not user_id or user_id == "default":
            for f in sorted(_WORKFLOWS_DIR.glob("*/workflow.json")):
                if f.parent.name == "_shared":
                    continue
                data = json.loads(f.read_text())
                agents = [Agent.from_dict(a) for a in data.get("agents", [])]
                node_order = build_dag(agents)
                edges = []
                conditional_edges = []
                for a in agents:
                    for dep in a.after or []:
                        edges.append([dep, a.name])
                    if a.on_pass is not None:
                        conditional_edges.append({"from": a.name, "to": a.on_pass, "label": "pass"})
                    if a.on_fail is not None:
                        conditional_edges.append({"from": a.name, "to": a.on_fail, "label": "fail"})
                agent_dicts = [a.to_dict() for a in agents]
                for ad in agent_dicts:
                    ad["description"] = _extract_description(ad["name"], f.parent)
                result.append({
                    "name": data["name"],
                    "agents": agent_dicts,
                    "dag": {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
                    "workflow_dir": str(f.parent),
                    "scope": "legacy",
                })

        # 4. Merge registry resources (builtin only — project-level already covered above)
        from harness.registry import get_registry
        registry = get_registry()
        existing_names = {r["name"] for r in result}
        for meta in registry.list_workflows(scope="builtin"):
            if meta.name in existing_names:
                continue
            wf_dir = meta.resource_dir
            wf_json = wf_dir / "workflow.json"
            if not wf_json.exists():
                continue
            try:
                data = json.loads(wf_json.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            agents = [Agent.from_dict(a) for a in data.get("agents", [])]
            node_order = build_dag(agents)
            edges = []
            conditional_edges = []
            for a in agents:
                for dep in a.after or []:
                    edges.append([dep, a.name])
                if a.on_pass is not None:
                    conditional_edges.append({"from": a.name, "to": a.on_pass, "label": "pass"})
                if a.on_fail is not None:
                    conditional_edges.append({"from": a.name, "to": a.on_fail, "label": "fail"})
            agent_dicts = [a.to_dict() for a in agents]
            for ad in agent_dicts:
                ad["description"] = _extract_description(ad["name"], wf_dir)
            result.append({
                "name": data["name"],
                "agents": agent_dicts,
                "dag": {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
                "workflow_dir": str(wf_dir),
                "scope": meta.scope,
                "description": meta.description,
            })

        return result

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "agents": [a.to_dict() for a in self.agents],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
        workflow_dir: Path | None = None,
        agents_dir: str | None = None,
        checkpointer: Any | None = None,
    ) -> Workflow:
        agents = [Agent.from_dict(a) for a in data.get("agents", [])]
        return cls(
            name=data["name"],
            agents=agents,
            workflow_dir=workflow_dir,
            agents_dir=agents_dir,
            checkpointer=checkpointer,
        )

    def run(self, inputs: dict, ui: bool = False, work_dir: str | None = None) -> WorkflowResult:
        """Run the workflow. Primary API — synchronous, simple.

        Args:
            inputs: Task input dict.
            ui: If True, auto-start server + open browser to visualize execution.
            work_dir: Working directory for agent file access and bash cwd.
                Defaults to os.getcwd(). Use "/" for full filesystem access.
        """
        if ui:
            self._launch_ui(inputs)
        return asyncio.run(self._execute(inputs, work_dir=work_dir))

    def _launch_ui(self, inputs: dict) -> None:
        """Start backend server and open browser for UI visualization."""
        import os
        import subprocess
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
            "name": self.name,
            "agents": [a.to_dict() for a in self.agents],
            "inputs": inputs,
        }).encode()
        req = ur.Request(f"http://localhost:{port}/api/workflows", data=data,
                         headers={"Content-Type": "application/json"})
        resp = ur.urlopen(req)
        result = json.loads(resp.read())
        wid = result["workflow_id"]

        # Open browser
        webbrowser.open(f"http://localhost:{port}?workflow={wid}")

    async def arun(self, inputs: dict | None = None, config: dict | None = None,
                   resume_value: Any | None = None) -> WorkflowResult:
        """Run the workflow asynchronously. For callers already in an async context.

        Caller is responsible for MCP lifecycle (call setup/cleanup if needed).

        Args:
            inputs: Task input dict. None when resuming.
            config: LangGraph run config. If checkpointer is set and no config
                provided, uses ``{'configurable': {'thread_id': self.name}}``.
            resume_value: Value to pass to LangGraph interrupt() on resume.
                When provided, uses Command(resume=resume_value) instead of
                initial_state to resume from an interrupted checkpoint.
        """
        if self.mcp_servers and not self._mcp_setup_done:
            raise RuntimeError(
                "MCP servers are configured but setup() was not called. "
                "Call await workflow.setup() before arun(), or use run() instead."
            )

        if self._compiled is None:
            self.compile()

        if config is None and self.checkpointer is not None:
            config = {"configurable": {"thread_id": self.name}}

        if resume_value is not None:
            from langgraph.types import Command
            final_state = await self._compiled.ainvoke(
                Command(resume=resume_value), config=config,
            )
        else:
            initial_state = {
                STATE_INPUTS: inputs or {},
                STATE_OUTPUTS: {},
                STATE_ERRORS: {},
                STATE_METADATA: {},
            }
            final_state = await self._compiled.ainvoke(initial_state, config=config)

        result = self._build_result(final_state)

        # Detect LangGraph interrupt: ainvoke returns {__interrupt__: [Interrupt(...)]}
        if isinstance(final_state, dict) and "__interrupt__" in final_state:
            interrupts = final_state["__interrupt__"]
            result.interrupted = True
            result.interrupt_value = interrupts[0].value if interrupts else None

        return result

    async def setup(self, work_dir: str | None = None):
        """Connect MCP servers and register their tools, then compile.

        For advanced usage with arun(). Not needed if using run().

        Args:
            work_dir: Working directory for MCP filesystem access.
                Defaults to os.getcwd(). Use "/" for full filesystem access.
        """
        if not self.tool_registry.list_tools():
            self.tool_registry = default_tool_registry(event_bus=self._event_bus)

        mcp_workdir = work_dir or os.getcwd()
        bridges: list[McpBridge] = []
        if self.enable_filesystem_mcp:
            try:
                bridges = await setup_default_mcp(self.tool_registry, workdir=mcp_workdir)
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
        if self.enable_codegraph_mcp:
            try:
                from harness.tools.defaults import setup_codegraph_mcp
                cg_bridge = await setup_codegraph_mcp(
                    self.tool_registry,
                    path=self.codegraph_path,
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

    async def _execute(self, inputs: dict, work_dir: str | None = None) -> WorkflowResult:
        """Internal: full lifecycle in one event loop.

        LangGraph's ainvoke() is auto-traced by LangSmith when
        LANGCHAIN_TRACING_V2=true, forming the top-level trace.
        """
        if work_dir is not None:
            p = Path(work_dir).resolve()
            if not p.exists():
                raise FileNotFoundError(f"Work directory does not exist: {work_dir}")
            if not p.is_dir():
                raise NotADirectoryError(f"Work path is not a directory: {work_dir}")
        await self.setup(work_dir=work_dir)
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


class Benchmark:
    """Declarative benchmark definition.

    Usage::

        bm = Benchmark("quantize-benchmark", description="量化评测")
        bm.prep(type="script", command="bash prep.sh", work_dir="/tmp/repos")
        bm.task("Quantize ResNet", inputs={"model": "resnet50"})
        bm.task("Quantize BERT", inputs={"model": "bert-base"})
        bm.save()

    Prep phase (optional):
        - ``type="script"``: runs a shell command before all tasks.
          Scripts live in ``benchmarks/<name>/``, added to PATH during execution.
          ``work_dir`` controls the execution directory (cwd).
        - ``type="agent"``: runs a single-agent workflow before all tasks.
          Agent MD resolved from ``benchmarks/<name>/agents/`` then ``workflows/_shared/agents/``.
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._prep: dict | None = None
        self._tasks: list[dict] = []

    def prep(
        self,
        type: Literal["script", "agent"],
        command: str | None = None,
        agent: str | None = None,
        work_dir: str | None = None,
    ) -> "Benchmark":
        """Set the prep phase for this benchmark."""
        p: dict = {"type": type}
        if command is not None:
            p["command"] = command
        if agent is not None:
            p["agent"] = agent
        if work_dir is not None:
            p["work_dir"] = work_dir
        self._prep = p
        return self

    def task(self, label: str, inputs: dict | None = None) -> "Benchmark":
        """Add a task to this benchmark."""
        self._tasks.append({
            "label": label,
            "inputs": inputs or {"task": label},
        })
        return self

    def save(self) -> Path:
        """Save benchmark definition to benchmarks/<name>/benchmark.json."""
        from harness.benchmark_store import BenchmarkStore
        store = BenchmarkStore()
        store.save_benchmark(
            name=self.name,
            tasks=self._tasks,
            description=self.description,
            prep=self._prep,
        )
        saved_path = (_BENCHMARKS_DIR / self.name / "benchmark.json").resolve()
        print(f"[Benchmark] saved → {saved_path}")
        return saved_path

    @classmethod
    def load(cls, name: str) -> "Benchmark":
        """Load a benchmark from benchmarks/<name>/benchmark.json."""
        from harness.benchmark_store import BenchmarkStore
        store = BenchmarkStore()
        data = store.load_benchmark(name)
        if data is None:
            raise FileNotFoundError(f"Benchmark '{name}' not found")
        bm = cls(name=data["name"], description=data.get("description", ""))
        bm._tasks = data.get("tasks", [])
        bm._prep = data.get("prep")
        return bm

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "description": self.description,
            "tasks": self._tasks,
        }
        if self._prep:
            d["prep"] = self._prep
        return d

    def run(self, workflow: str, ui: bool = False, plugins: list | None = None) -> "BenchmarkResult":
        """Run this benchmark with the specified workflow. Synchronous.

        Executes prep (if defined), then runs all tasks in parallel.

        Args:
            workflow: Name of the workflow to use for all tasks.
            ui: If True, auto-start server + open browser.
            plugins: Extensions (Hook/Middleware/GraphMutator) to register on each
                     task's Workflow. E.g. ``plugins=[ConsoleOutput()]``
        """
        return asyncio.run(self._execute(workflow, ui=ui, plugins=plugins))

    async def arun(self, workflow: str, plugins: list | None = None) -> "BenchmarkResult":
        """Run this benchmark asynchronously. For callers already in async context."""
        return await self._execute(workflow, ui=False, plugins=plugins)

    async def _execute(self, workflow_name: str, ui: bool = False, plugins: list | None = None) -> "BenchmarkResult":
        # 1. Resolve workflow definition
        from harness.registry import get_registry
        try:
            wf_dir = get_registry().resolve_workflow(workflow_name).resource_dir
        except FileNotFoundError:
            wf_dir = _WORKFLOWS_DIR / workflow_name
            if not wf_dir.exists():
                wf_dir = _WORKFLOWS_DIR / "_shared" / "workflows" / workflow_name
        if not (wf_dir / "workflow.json").exists():
            raise FileNotFoundError(f"Workflow '{workflow_name}' not found")

        wf_data = json.loads((wf_dir / "workflow.json").read_text())
        agents_defs = wf_data.get("agents", [])

        # 2. Run prep phase
        if self._prep:
            from harness.prep_executor import run_prep, PrepError
            await run_prep(self._prep, benchmark_name=self.name)

        # 3. Run all tasks in parallel
        coros = []
        task_labels = []
        for t in self._tasks:
            agents = [Agent.from_dict(a) for a in agents_defs]
            task_wf = Workflow(
                name=f"{self.name}/{t['label']}",
                agents=agents,
                workflow_dir=wf_dir,
                tool_registry=ToolRegistry(),
            )
            # Register plugins on each task's workflow
            if plugins:
                for ext in plugins:
                    task_wf.use(ext)
            inputs = t.get("inputs", {"task": t["label"]})
            coros.append(task_wf._execute(inputs))
            task_labels.append(t["label"])

        results = await asyncio.gather(*coros, return_exceptions=True)

        # 4. Build result
        task_results = []
        for label, r in zip(task_labels, results):
            if isinstance(r, Exception):
                task_results.append(BenchmarkTaskResult(
                    label=label, status="failed", error=str(r),
                ))
            else:
                task_results.append(BenchmarkTaskResult(
                    label=label, status="completed", result=r,
                ))

        bm_result = BenchmarkResult(
            benchmark_name=self.name,
            workflow_name=workflow_name,
            tasks=task_results,
        )

        # 5. UI mode
        if ui:
            self._launch_benchmark_ui(bm_result)

        return bm_result

    def _launch_benchmark_ui(self, result: "BenchmarkResult") -> None:
        import subprocess
        import time
        import threading

        port = int(os.environ.get("HARNESS_PORT", "8000"))
        import urllib.request
        try:
            urllib.request.urlopen(f"http://localhost:{port}/health", timeout=1)
        except Exception:
            def _start():
                import uvicorn
                uvicorn.run("server.app:app", host="0.0.0.0", port=port, log_level="warning")
            t = threading.Thread(target=_start, daemon=True)
            t.start()
            time.sleep(2)

        webbrowser.open(f"http://localhost:{port}")


class BenchmarkTaskResult(BaseModel):
    """Result of a single task within a benchmark run."""
    label: str
    status: Literal["completed", "failed"]
    result: WorkflowResult | None = None
    error: str | None = None


class BenchmarkResult(BaseModel):
    """Result of a full benchmark run."""
    benchmark_name: str
    workflow_name: str
    tasks: list[BenchmarkTaskResult]

    @property
    def all_completed(self) -> bool:
        return all(t.status == "completed" for t in self.tasks)

    @property
    def failed_tasks(self) -> list[BenchmarkTaskResult]:
        return [t for t in self.tasks if t.status == "failed"]
