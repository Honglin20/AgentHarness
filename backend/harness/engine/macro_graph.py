from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from langgraph.graph import StateGraph, START, END

from harness.api import Agent
from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import parse_agent_md
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState


class MacroGraphBuilder:
    """将编译后的 DAG 转为 LangGraph StateGraph。"""

    def __init__(self, micro_factory: MicroAgentFactory | None = None):
        self.micro_factory = micro_factory or MicroAgentFactory()

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

        # Add nodes
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

    def _make_node_func(self, agent_def, parsed, dep_map):
        """Create a LangGraph node function for an agent."""
        micro_factory = self.micro_factory

        # Merge tools: MD default + API append
        md_tools = parsed.tools
        api_tools = agent_def.tools or []
        final_tools = md_tools + [t for t in api_tools if t not in md_tools]

        # Merge model: API > MD > default
        model = agent_def.model or parsed.model

        # Use MD retries as source of truth
        retries = parsed.retries
        result_type = agent_def.result_type

        # Create the Pydantic AI agent
        pydantic_agent = micro_factory.create(
            name=agent_def.name,
            prompt=parsed.prompt,
            tools=final_tools,
            model=model,
            retries=retries,
            result_type=result_type,
        )

        upstream_names = dep_map[agent_def.name]

        def node_func(state: HarnessState) -> dict:
            start_time = time.time()

            # Gather upstream outputs
            upstream_outputs = {}
            outputs = state.get("outputs", {})
            for dep_name in upstream_names:
                if dep_name in outputs:
                    upstream_outputs[dep_name] = outputs[dep_name]

            # Build the full prompt
            full_prompt = micro_factory.build_node_prompt(
                md_prompt=parsed.prompt,
                inputs=state.get("inputs", {}),
                upstream_outputs=upstream_outputs,
            )

            # Run the Pydantic AI agent
            try:
                result = pydantic_agent.run_sync(full_prompt)
                duration_ms = int((time.time() - start_time) * 1000)
                return {
                    "outputs": {agent_def.name: result.data},
                    "errors": {},
                    "metadata": {agent_def.name: {"duration_ms": duration_ms}},
                }
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                return {
                    "outputs": {},
                    "errors": {agent_def.name: str(e)},
                    "metadata": {agent_def.name: {"duration_ms": duration_ms}},
                }

        return node_func
