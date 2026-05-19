from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from langgraph.graph import StateGraph, START, END

from harness.api import Agent
from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import parse_agent_md
from harness.constants import STATE_ERRORS, STATE_INPUTS, STATE_METADATA, STATE_OUTPUTS
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolRegistry
from harness.instrumentation import trace_agent


class MacroGraphBuilder:
    """将编译后的 DAG 转为 LangGraph StateGraph。"""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,  # Optional EventBus for emitting events
    ):
        self.tool_registry = tool_registry or ToolRegistry()
        self.event_bus = event_bus  # Store for use in node functions

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

        # Build execution order
        execution_order = build_dag(agents)

        # Build dependency map
        dep_map = {a.name: a.after for a in agents}
        agent_map = {a.name: a for a in agents}

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

        # Add edges from leaf nodes to END
        downstream = set()
        for deps in dep_map.values():
            downstream.update(deps)
        for agent_name in execution_order:
            if agent_name not in downstream:
                graph.add_edge(agent_name, END)

        return graph

    def add_conditional_edge(self, from_node, condition_fn, targets):
        raise NotImplementedError("Conditional edges are planned for Phase 2+")

    def add_evaluator_edge(self, eval_node, pass_target, fail_target):
        raise NotImplementedError("Evaluator edges are planned for Phase 4")

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

        return final_tool_names, model, retries, result_type

    def _make_node_func(self, agent_def, parsed, dep_map):
        """Create an async LangGraph node function for an agent."""
        micro_factory = self.micro_factory
        bus = self.event_bus  # Capture for closure
        final_tool_names, model, retries, result_type = self._resolve_agent_config(agent_def, parsed)
        upstream_names = dep_map[agent_def.name]

        async def node_func(state: HarnessState) -> dict:
            start_time = time.time()

            # Emit node.started event
            if bus:
                bus.emit("node.started", {
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

            # Create stream callback if event_bus is present
            def make_stream_callback(node_id: str, agent_name: str):
                def stream_callback(text: str) -> None:
                    """Called for each partial result chunk."""
                    if bus:
                        bus.emit("agent.text_delta", {
                            "node_id": node_id,
                            "agent_name": agent_name,
                            "text": text,
                        })
                return stream_callback

            stream_callback = make_stream_callback(agent_def.name, agent_def.name) if bus else None

            # Create the Pydantic AI agent with resolved tools
            pydantic_agent = micro_factory.create(
                name=agent_def.name,
                prompt=parsed.prompt,
                tools=final_tool_names,
                model=model,
                retries=retries,
                result_type=result_type,
                deps=deps,
                stream_callback=stream_callback,
            )

            # Run the Pydantic AI agent (async) — traced via LangSmith
            with trace_agent(agent_def.name, inputs={"context": context}) as ls_run:
                try:
                    if bus:
                        # Use streaming
                        result_chunks = []
                        async for chunk in pydantic_agent.run_stream(context, deps=deps):
                            result_chunks.append(chunk)
                        # Concatenate partial results
                        result = "".join(result_chunks)
                    else:
                        # Use non-streaming
                        result = await pydantic_agent.run(context, deps=deps)

                    duration_ms = int((time.time() - start_time) * 1000)

                    # Emit node.completed event
                    if bus:
                        bus.emit("node.completed", {
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "duration_ms": duration_ms,
                            "status": "success",
                        })

                    if ls_run:
                        try:
                            usage = result.usage()
                            ls_run.end(
                                outputs={"result": str(result.output)},
                                metadata={
                                    "token_usage": {
                                        "input": usage.request_tokens,
                                        "output": usage.response_tokens,
                                        "total": usage.total_tokens,
                                    }
                                },
                            )
                        except Exception:
                            ls_run.end(outputs={"result": str(result.output)})

                    return {
                        STATE_OUTPUTS: {agent_def.name: result.output},
                        STATE_ERRORS: {},
                        STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                    }
                except Exception as e:
                    duration_ms = int((time.time() - start_time) * 1000)

                    # Emit node.failed event
                    if bus:
                        bus.emit("node.failed", {
                            "node_id": agent_def.name,
                            "agent_name": agent_def.name,
                            "error": str(e),
                            "duration_ms": duration_ms,
                            "attempt": 1,
                            "will_retry": False,
                        })

                    if ls_run:
                        ls_run.end(error=str(e))

                    return {
                        STATE_OUTPUTS: {},
                        STATE_ERRORS: {agent_def.name: str(e)},
                        STATE_METADATA: {agent_def.name: {"duration_ms": duration_ms}},
                    }

        return node_func
