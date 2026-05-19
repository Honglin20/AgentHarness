from __future__ import annotations

import json
from typing import Type

from pydantic import BaseModel
from pydantic_ai import Agent as PydanticAgent


DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


class MicroAgentFactory:
    """为每个 DAG 节点生成 Pydantic AI Agent 实例。"""

    def create(
        self,
        name: str,
        prompt: str,
        tools: list[str],
        model: str | None,
        retries: int,
        result_type: Type[BaseModel] | None,
    ) -> PydanticAgent:
        """Create a Pydantic AI Agent instance for a DAG node.

        Note: Tool resolution (name → callable) is deferred to Phase 2.
        Phase 1 agents run without tools.
        """
        agent_model = model or DEFAULT_MODEL
        if ":" not in agent_model:
            agent_model = f"anthropic:{agent_model}"

        agent = PydanticAgent(
            model=agent_model,
            system_prompt=prompt,
            retries=retries,
            output_type=result_type or str,
            defer_model_check=True,
        )
        return agent

    def build_node_prompt(
        self,
        md_prompt: str,
        inputs: dict,
        upstream_outputs: dict,
    ) -> str:
        """Build the complete prompt for a node.

        Automatically injects inputs (## Task) and upstream outputs
        (## Output from X). Agent authors do not write template syntax.
        """
        parts = [md_prompt]

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
