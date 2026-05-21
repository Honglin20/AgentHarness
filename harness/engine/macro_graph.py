from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from pydantic_graph import End

from harness.api import Agent
from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import parse_agent_md
from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolRegistry


# --- Interrupt signal management ---
_pending_interrupts: dict[str, str] = {}  # workflow_id → directive
_interrupt_lock = asyncio.Lock()


async def request_interrupt(workflow_id: str, directive: str) -> None:
    """Called from WebSocket handler when user requests an interrupt."""
    async with _interrupt_lock:
        _pending_interrupts[workflow_id] = directive


def _has_pending_interrupt(workflow_id: str) -> bool:
    return workflow_id in _pending_interrupts


def _consume_interrupt(workflow_id: str) -> str | None:
    return _pending_interrupts.pop(workflow_id, None)


class ReviewDecision(BaseModel):
    """Default result_type for agents with conditional edges."""
    decision: Literal["pass", "fail"]
    reason: str


class MacroGraphBuilder:
    """将编译后的 DAG 转为 LangGraph StateGraph。"""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,
        max_iterations: int = 3,
    ):
        self.tool_registry = tool_registry or ToolRegistry()
        self.event_bus = event_bus
        self.max_iterations = max_iterations
        self.workflow_id: str | None = None  # Set by runner before execution

        # Register event-bus-dependent tools when event_bus is available
        if event_bus and "ask_human" not in self.tool_registry.list_tools():
            from harness.tools.ask_human import AskHumanToolFactory
            self.tool_registry.register("ask_human", AskHumanToolFactory(event_bus=event_bus))

        self.micro_factory = MicroAgentFactory(tool_registry=self.tool_registry)

    def build(self, workflow) -> StateGraph:
        """Build a LangGraph StateGraph from a Workflow definition."""
        agents = workflow.agents
        agents_dir = Path(workflow.agents_dir)

        # Parse all agent MD files
        parsed_agents = {}
        for agent in agents:
            md_path = agents_dir / f"{agent.name}.md"
            parsed = parse_agent_md(md_path)
            parsed_agents[agent.name] = parsed

        # Build execution order (static edges only)
        execution_order = build_dag(agents)

        # Build dependency map
        dep_map = {a.name: a.after for a in agents}
        agent_map = {a.name: a for a in agents}

        # Merge on_pass/on_fail from parsed MD into agent defs
        for agent in agents:
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
            parsed = parsed_agents[agent_name]
            node_func = self._make_node_func(agent_def, parsed, dep_map)
            graph.add_node(agent_name, node_func)

        # Add edges from START to root nodes
        for agent_name in execution_order:
            if not dep_map[agent_name]:
                graph.add_edge(START, agent_name)

        # Add edges between dependent nodes
        for agent_name in execution_order:
            for dep in dep_map[agent_name]:
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

                graph.add_conditional_edges(
                    agent.name,
                    lambda state, an=agent.name: _route_decision(state, an),
                    targets,
                )

        # Add edges from leaf nodes to END (only if no conditional edges)
        downstream = set()
        for deps in dep_map.values():
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

    def _resolve_agent_config(self, agent_def, parsed):
        """Merge tools, model, retries from API definition and MD file.

        Returns (final_tool_names, model, retries, result_type).
        """
        md_tools = parsed.tools
        api_tools = agent_def.tools or []
        if not md_tools and not api_tools:
            final_tool_names = None  # → resolve() loads all
        else:
            final_tool_names = md_tools + [t for t in api_tools if t not in md_tools]

        model = agent_def.model or parsed.model
        retries = parsed.retries
        result_type = agent_def.result_type

        # Auto-inject ReviewDecision if agent has conditional edges and no result_type
        if agent_def.has_conditional_edges and result_type is None:
            result_type = ReviewDecision

        return final_tool_names, model, retries, result_type

    def _make_node_func(self, agent_def, parsed, dep_map):
        """Create an async LangGraph node function for an agent."""
        micro_factory = self.micro_factory
        bus = self.event_bus
        max_iterations = self.max_iterations
        builder_self = self  # Capture for workflow_id access
        final_tool_names, model, retries, result_type = self._resolve_agent_config(agent_def, parsed)
        upstream_names = dep_map[agent_def.name]

        async def node_func(state: HarnessState) -> dict:
            start_time = time.time()

            # Check iteration count for conditional edges
            if agent_def.has_conditional_edges:
                iter_key = f"{agent_def.name}_loop"
                current_count = state.get("iteration_counts", {}).get(iter_key, 0)
                if current_count >= max_iterations:
                    if bus:
                        bus.emit("node.failed", {
                            "workflow_id": builder_self.workflow_id,
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "error": f"Max iterations ({max_iterations}) reached for conditional edge loop",
                            "duration_ms": 0,
                            "attempt": 1,
                            "will_retry": False,
                        })
                    return {
                        STATE_OUTPUTS: {},
                        STATE_ERRORS: {agent_def.name: f"Max iterations ({max_iterations}) exceeded"},
                        STATE_METADATA: {},
                        "iteration_counts": {iter_key: current_count},
                    }

            # Emit node.started event
            if bus:
                bus.emit("node.started", {
                    "workflow_id": builder_self.workflow_id,
                    "node_id": agent_def.name,
                    "agent_name": agent_def.name,
                    "attempt": 1,
                })

            # Gather upstream outputs
            upstream_outputs = {}
            outputs = state.get(STATE_OUTPUTS, {})
            for dep_name in upstream_names:
                if dep_name in outputs:
                    upstream_outputs[dep_name] = outputs[dep_name]

            # Build deps for this agent
            deps = AgentDeps(agent_name=agent_def.name)

            # Build the context (user message) — system prompt is already set via md_prompt
            context = micro_factory.build_node_prompt(
                inputs=state.get(STATE_INPUTS, {}),
                upstream_outputs=upstream_outputs,
            )

            # Create the Pydantic AI agent with resolved tools
            pydantic_agent = micro_factory.create(
                name=agent_def.name,
                prompt=parsed.prompt,
                tools=final_tool_names,
                model=model,
                retries=retries,
                result_type=result_type,
                deps=deps,
            )

            # Run the Pydantic AI agent (async)
            # Use iter() instead of run_stream() so that tool calls are fully executed.
            # run_stream() treats the first text output as "final result" and skips
            # subsequent tool calls (pydantic_ai end_strategy='early' default).
            try:
                directive = None
                wid = builder_self.workflow_id if bus else None

                async def _run_agent(user_context: str):
                    """Run agent via iter() — executes tools fully, streams text + tool events."""
                    nonlocal directive
                    async with pydantic_agent.iter(user_context, deps=deps) as agent_run:
                        node = agent_run.next_node
                        while not isinstance(node, End):
                            if pydantic_agent.is_model_request_node(node):
                                async with node.stream(agent_run.ctx) as stream:
                                    async for chunk in stream.stream_text(delta=True):
                                        if bus:
                                            bus.emit("agent.text_delta", {
                                                "workflow_id": wid,
                                                "node_id": agent_def.name,
                                                "agent_name": agent_def.name,
                                                "text": chunk,
                                            })
                                        if wid and _has_pending_interrupt(wid):
                                            directive = _consume_interrupt(wid)
                                            break
                                if directive:
                                    break
                                node = await agent_run.next(node)

                            elif pydantic_agent.is_call_tools_node(node):
                                if bus:
                                    async with node.stream(agent_run.ctx) as stream:
                                        async for event in stream:
                                            ek = getattr(event, 'event_kind', '')
                                            if ek == 'function_tool_call':
                                                part = event.part
                                                bus.emit("agent.tool_call", {
                                                    "workflow_id": wid,
                                                    "node_id": agent_def.name,
                                                    "agent_name": agent_def.name,
                                                    "tool_name": part.tool_name,
                                                    "tool_args": part.args if hasattr(part, 'args') else {},
                                                })
                                            elif ek == 'function_tool_result':
                                                part = event.part
                                                bus.emit("agent.tool_result", {
                                                    "workflow_id": wid,
                                                    "node_id": agent_def.name,
                                                    "agent_name": agent_def.name,
                                                    "tool_name": part.tool_name,
                                                    "result": str(part.content) if hasattr(part, 'content') else "",
                                                })
                                else:
                                    async with node.stream(agent_run.ctx) as stream:
                                        async for _ in stream:
                                            pass
                                node = await agent_run.next(node)

                            else:
                                node = await agent_run.next(node)

                        return agent_run

                agent_run = await _run_agent(context)

                if directive:
                    bus.emit("agent.text_delta", {
                        "workflow_id": wid,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "text": "\n\n--- [用户打断指令]: " + directive + " ---\n\n",
                    })
                    new_context = context + f"\n\n[用户打断指令]: {directive}"
                    agent_run = await _run_agent(new_context)

                    bus.emit("workflow.resumed", {
                        "workflow_id": wid,
                        "node_id": agent_def.name,
                        "directive": directive,
                    })
                    directive = None

                output = agent_run.result.output
                usage_obj = agent_run.usage

                duration_ms = int((time.time() - start_time) * 1000)

                # Extract token usage
                token_usage = None
                try:
                    token_usage = {
                        "input": usage_obj.input_tokens,
                        "output": usage_obj.output_tokens,
                        "total": usage_obj.total_tokens,
                    }
                except Exception:
                    pass

                node_meta = {"duration_ms": duration_ms}
                if token_usage:
                    node_meta["token_usage"] = token_usage

                # Emit node.completed event
                if bus:
                    event_payload = {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "duration_ms": duration_ms,
                        "status": "success",
                    }
                    if token_usage:
                        event_payload["token_usage"] = token_usage
                    bus.emit("node.completed", event_payload)

                # Build iteration_counts update for conditional edges
                iter_update = {}
                if agent_def.has_conditional_edges:
                    iter_key = f"{agent_def.name}_loop"
                    # Determine decision from output
                    decision = _extract_decision(output)
                    if decision == "fail" and agent.on_fail is not None:
                        iter_update[iter_key] = state.get("iteration_counts", {}).get(iter_key, 0) + 1

                result_dict = {
                    STATE_OUTPUTS: {agent_def.name: output},
                    STATE_ERRORS: {},
                    STATE_METADATA: {agent_def.name: node_meta},
                }
                if iter_update:
                    result_dict["iteration_counts"] = iter_update

                return result_dict
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)

                if bus:
                    bus.emit("node.failed", {
                        "workflow_id": builder_self.workflow_id,
                        "node_id": agent_def.name,
                        "agent_name": agent_def.name,
                        "error": str(e),
                        "duration_ms": duration_ms,
                        "attempt": 1,
                        "will_retry": False,
                    })

                return {
                    STATE_OUTPUTS: {},
                    STATE_ERRORS: {agent_def.name: str(e)},
                    STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                }

        return node_func


def _route_decision(state: HarnessState, agent_name: str) -> str:
    """Route based on the decision field in the agent's output."""
    outputs = state.get(STATE_OUTPUTS, {})
    output = outputs.get(agent_name)

    decision = _extract_decision(output)
    return decision if decision in ("pass", "fail") else "pass"


def _extract_decision(output: Any) -> str:
    """Extract decision from agent output, which may be a ReviewDecision model or a string."""
    if isinstance(output, ReviewDecision):
        return output.decision
    if isinstance(output, BaseModel):
        decision = getattr(output, "decision", None)
        if decision:
            return str(decision)
    if isinstance(output, str):
        lower = output.lower()
        if "fail" in lower:
            return "fail"
    return "pass"
