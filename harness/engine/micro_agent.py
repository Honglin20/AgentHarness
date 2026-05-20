from __future__ import annotations

import json
from typing import Type

from pydantic import BaseModel
from pydantic_ai import Agent as PydanticAgent

from harness.tools.deps import AgentDeps
from harness.constants import DEFAULT_MODEL
from harness.engine.llm import LLMClient
from harness.tools.registry import ToolRegistry


class MicroAgentFactory:
    """为每个 DAG 节点生成 Pydantic AI Agent 实例。"""

    def __init__(self, tool_registry: ToolRegistry | None = None):
        self.tool_registry = tool_registry or ToolRegistry()

    def create(
        self,
        name: str,
        prompt: str,
        tools: list[str] | None,
        model: str | None,
        retries: int,
        result_type: Type[BaseModel] | None,
        deps: AgentDeps | None = None,
        exclude_tools: list[str] | None = None,
    ) -> PydanticAgent:
        agent_model = model or DEFAULT_MODEL
        if not agent_model:
            raise RuntimeError(
                "No model configured. Set HARNESS_MODEL env var (e.g. 'gpt-4o') "
                "or pass model=... to Agent().\n"
                "Run: python config_llm.py  or  export HARNESS_MODEL='gpt-4o'"
            )

        resolved_tools = self.tool_registry.resolve(tools, exclude=exclude_tools)

        client = LLMClient(model=agent_model) if model else LLMClient()
        agent = client.agent(
            system_prompt=prompt,
            output_type=result_type or str,
            retries=retries,
            tools=resolved_tools,
            deps_type=AgentDeps,
        )

        return agent

    def build_node_prompt(
        self,
        inputs: dict,
        upstream_outputs: dict,
    ) -> str:
        """Build the context portion of a node's prompt.

        Generates ## Task (from inputs) and ## Output from X (from upstream).
        This is passed as the user message; the agent's md_prompt is the system prompt.
        """
        parts = []

        if inputs:
            parts.append(f"## Task\n{json.dumps(inputs, indent=2, ensure_ascii=False)}")

        for name, output in upstream_outputs.items():
            if isinstance(output, BaseModel):
                parts.append(
                    f"## Output from {name}\n{output.model_dump_json(indent=2)}"
                )
            else:
                parts.append(f"## Output from {name}\n{output}")

        return "\n\n".join(parts)
