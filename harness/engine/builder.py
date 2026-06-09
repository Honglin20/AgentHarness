"""``MacroGraphBuilder`` — compiles a declarative Workflow into a LangGraph StateGraph.

This module hosts the class only; the heavy per-node closure lives in
``node_factory.py``, stop/regenerate signal routing in ``stop_regen.py``,
incremental persistence in ``incremental_save.py``, and conditional-edge
routing in ``routing.py``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.graph import StateGraph, START, END

from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import (
    ParsedAgent,
    parse_agent_md,
    resolve_agent_md,
)
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.node_factory import (
    make_node_func,
    make_passthrough_node_func,
    resolve_agent_config,
)
from harness.engine.routing import _route_decision
from harness.engine.state import HarnessState
from harness.engine.stop_signal import StopSignalManager
from harness.engine.stop_regen import _active_builders
from harness.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class MacroGraphBuilder:
    """Compile a declarative Workflow definition into a LangGraph StateGraph."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,
        max_iterations: int = 3,
        envelope: dict[str, int] | None = None,
        request_limit: int | None = None,
    ):
        self.tool_registry = tool_registry or ToolRegistry()
        self.event_bus = event_bus
        self.max_iterations = max_iterations
        self.envelope = envelope
        # Per-agent request budget (None → HARNESS_REQUEST_LIMIT env, default 200).
        # Forwarded to micro_factory.create() inside node_factory.
        self.request_limit = request_limit
        self.workflow_id: str | None = None  # Set by runner before execution
        self._workflow_name: str = ""  # Set by build()
        self.agent_io: dict[str, dict] = {}  # Collected per-node I/O for persistence

        # Stop-and-regenerate signal management (delegated to StopSignalManager)
        self._signal_mgr = StopSignalManager()

        # ChatGPT-style stop: asyncio.Event-based guidance waiting.
        # These fields are kept for backward compatibility with tests that
        # access them directly. They delegate to _signal_mgr.
        # When Stop is clicked with empty guidance, nodeFunc emits
        # workflow.waiting_for_guidance and awaits this event.
        # When user submits guidance, provide_guidance() sets it.

        # Register event-bus-dependent tools when event_bus is available
        if event_bus:
            if "ask_user" not in self.tool_registry.list_tools():
                from harness.tools.ask_user import AskUserToolFactory
                self.tool_registry.register("ask_user", AskUserToolFactory(event_bus=event_bus))
            if "render_chart" not in self.tool_registry.list_tools():
                from harness.tools.chart import RenderChartToolFactory
                self.tool_registry.register("render_chart", RenderChartToolFactory(event_bus=event_bus))

        self.micro_factory = MicroAgentFactory(tool_registry=self.tool_registry)

    # ---- Stop & Regenerate instance methods (delegate to StopSignalManager) ----

    @property
    def _guidance_event(self) -> asyncio.Event | None:
        """Backward-compatible property for tests."""
        wid = self.workflow_id or ""
        return self._signal_mgr._guidance_events.get(wid)

    @_guidance_event.setter
    def _guidance_event(self, value: asyncio.Event | None) -> None:
        wid = self.workflow_id or ""
        if value is None:
            self._signal_mgr._guidance_events.pop(wid, None)
        else:
            self._signal_mgr._guidance_events[wid] = value

    @property
    def _pending_guidance(self) -> str:
        """Backward-compatible property for tests."""
        wid = self.workflow_id or ""
        return self._signal_mgr._guidance_values.get(wid, "")

    @_pending_guidance.setter
    def _pending_guidance(self, value: str) -> None:
        wid = self.workflow_id or ""
        self._signal_mgr._guidance_values[wid] = value

    @property
    def _pending_stop_regen(self) -> dict[str, dict[str, str | float]]:
        """Backward-compatible property for tests."""
        return self._signal_mgr._pending

    async def request_stop_and_regenerate(
        self,
        agent_name: str,
        partial_output: str,
        user_guidance: str,
    ) -> None:
        """Request stop + regenerate for a specific agent in this workflow.

        Delegates to StopSignalManager.store().
        """
        wid = self.workflow_id or ""
        await self._signal_mgr.store(wid, agent_name, partial_output, user_guidance)

    async def await_guidance(self, timeout: float = 300.0) -> str:
        """Block until user provides guidance via provide_guidance().

        Returns the guidance string, or "" on timeout.
        Delegates to StopSignalManager.await_guidance().
        """
        wid = self.workflow_id or ""
        return await self._signal_mgr.await_guidance(wid, timeout=timeout)

    async def provide_guidance(self, guidance: str) -> None:
        """Set guidance and wake up the waiting nodeFunc.

        Delegates to StopSignalManager.provide_guidance().
        """
        wid = self.workflow_id or ""
        await self._signal_mgr.provide_guidance(wid, guidance)

    def _has_pending_stop_regen(self, workflow_id: str, agent_name: str) -> bool:
        """Check if there's a pending signal. Delegates to StopSignalManager."""
        return self._signal_mgr.has_pending(workflow_id, agent_name)

    def _consume_stop_regen(self, workflow_id: str) -> dict[str, str] | None:
        """Consume and return the signal. Delegates to StopSignalManager."""
        return self._signal_mgr.consume(workflow_id)

    def register_active(self) -> None:
        """Register this builder as the active one for its workflow_id.

        Called by runner after setting workflow_id.  Enables the module-level
        request_stop_and_regenerate shim to forward signals here.
        """
        if self.workflow_id:
            _active_builders[self.workflow_id] = self

    def unregister_active(self) -> None:
        if self.workflow_id:
            _active_builders.pop(self.workflow_id, None)

    def build(self, workflow) -> StateGraph:
        """Build a LangGraph StateGraph from a Workflow definition.

        Mutators are invoked by ``Workflow.compile()`` (two-phase mutate+persist),
        not here. By the time we see the workflow, the DAG is final.
        """
        self._workflow_name = workflow.name

        agents = workflow.agents
        workflow_dir = workflow.workflow_dir

        # Parse all agent MD files via resolve_agent_md (private first, shared fallback)
        # Skip passthrough nodes (no MD on disk)
        parsed_agents = {}
        agent_md_paths = {}
        for agent in agents:
            if "_passthrough" in agent.name:
                continue  # passthrough node — no MD file
            try:
                md_path = resolve_agent_md(agent.name, workflow_dir)
                agent_md_paths[agent.name] = str(md_path)
                parsed = parse_agent_md(md_path)
            except (FileNotFoundError, ValueError):
                # MD missing or malformed (e.g. idempotent re-compile after
                # external corruption). Fall back to bare prompt — the agent
                # definition in workflow.json carries result_type and tools.
                parsed = ParsedAgent(name=agent.name, prompt="")
            parsed_agents[agent.name] = parsed

        # Build execution order (static edges only)
        execution_order = build_dag(agents)

        # Build dependency map
        dep_map = {a.name: a.after for a in agents}
        agent_map = {a.name: a for a in agents}

        # Build judge→target mapping for upstream injection.
        # When a downstream agent depends on a judge, it also needs the
        # judge's eval_target output (e.g. runner needs configurator's
        # AdapterConfig, not the judge's ReviewDecision).
        judge_targets = {}
        for agent in agents:
            et = getattr(agent, "eval_target", None) or getattr(agent, "_eval_target", None)
            if et:
                judge_targets[agent.name] = et

        # Merge on_pass/on_fail from parsed MD into agent defs
        for agent in agents:
            if agent.name not in parsed_agents:
                continue
            parsed = parsed_agents[agent.name]
            if agent.on_pass is None and parsed.on_pass is not None:
                agent.on_pass = parsed.on_pass
            if agent.on_fail is None and parsed.on_fail is not None:
                agent.on_fail = parsed.on_fail

        # Build the StateGraph
        graph = StateGraph(HarnessState)

        # Add nodes (async node functions)
        for agent_name in execution_order:
            agent_def = agent_map[agent_name]
            is_passthrough = "_passthrough" in agent_name

            if is_passthrough:
                node_func = make_passthrough_node_func(agent_def)
            else:
                parsed = parsed_agents[agent_name]
                node_func = make_node_func(
                    self, agent_def, parsed, dep_map, workflow_dir,
                    agent_md_paths.get(agent_name, ""), judge_targets,
                )
            graph.add_node(agent_name, node_func)

        # Collect conditional edge targets — these are activated by routing,
        # not by START, even if they have no `after` dependency.
        # Exception: a node that is a root (no deps) should still get START edge
        # even if it's a conditional target (for retry/loop scenarios).
        conditional_targets = set()
        # Track agents with after=None (only trigger via conditional edges)
        conditional_only_nodes = set()
        # Track source nodes that have conditional edges — their outgoing
        # routing is fully controlled by conditional edges, so static edges
        # from them must be skipped to avoid conflicting paths.
        conditional_source_nodes = set()
        for agent in agents:
            if agent.after is None:
                conditional_only_nodes.add(agent.name)
            if agent.has_conditional_edges:
                conditional_source_nodes.add(agent.name)
                if agent.on_pass is not None:
                    conditional_targets.add(agent.on_pass)
                if agent.on_fail is not None:
                    conditional_targets.add(agent.on_fail)

        # Build a set of root nodes (agents with no static dependencies)
        root_nodes = {agent_name for agent_name, deps in dep_map.items() if deps is not None and not deps}

        # Add edges from START to root nodes
        # Exclude nodes that are conditional-only (after=None)
        # Include root nodes that are also conditional targets (for retry/loop)
        for agent_name in execution_order:
            if agent_name in root_nodes and agent_name not in conditional_only_nodes:
                graph.add_edge(START, agent_name)

        # Add edges between dependent nodes
        # Skip static edges FROM nodes that have conditional edges — their
        # routing is handled entirely by add_conditional_edges below.
        for agent_name in execution_order:
            deps = dep_map[agent_name] or []
            for dep in deps:
                if dep in conditional_source_nodes:
                    continue
                graph.add_edge(dep, agent_name)

        # Track which nodes have conditional edges
        conditional_nodes = set()

        # Add conditional edges for agents with on_pass/on_fail
        for agent in agents:
            if agent.has_conditional_edges:
                conditional_nodes.add(agent.name)
                targets = {}
                targets["pass"] = agent.on_pass if agent.on_pass is not None else END
                targets["fail"] = agent.on_fail if agent.on_fail is not None else END

                # All nodes route from outputs (ReviewDecision.decision or
                # plain string) — no metadata special-casing.
                router = lambda state, an=agent.name: _route_decision(state, an)

                graph.add_conditional_edges(
                    agent.name,
                    router,
                    targets,
                )

        # Add edges from leaf nodes to END (only if no conditional edges)
        downstream = set()
        for deps in dep_map.values():
            if deps:
                downstream.update(deps)
        # Add conditional edge targets to downstream
        for agent in agents:
            if agent.on_pass is not None:
                downstream.add(agent.on_pass)
            if agent.on_fail is not None:
                downstream.add(agent.on_fail)

        for agent_name in execution_order:
            if agent_name not in downstream and agent_name not in conditional_nodes:
                graph.add_edge(agent_name, END)

        return graph

    # ---- Backward-compat thin wrappers (instance API preserved) ----

    def _resolve_agent_config(self, agent_def, parsed):
        """Backward-compat wrapper; logic lives in node_factory.resolve_agent_config."""
        return resolve_agent_config(self, agent_def, parsed)

    def _make_node_func(self, agent_def, parsed, dep_map, workflow_dir, md_path="", judge_targets=None):
        """Backward-compat wrapper; logic lives in node_factory.make_node_func."""
        return make_node_func(self, agent_def, parsed, dep_map, workflow_dir, md_path, judge_targets)

    def _make_passthrough_node_func(self, agent_def):
        """Backward-compat wrapper; logic lives in node_factory.make_passthrough_node_func."""
        return make_passthrough_node_func(agent_def)
