from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel
from pydantic_ai import Agent as PydanticAgent

from harness.tools.deps import AgentDeps
from harness.constants import DEFAULT_MODEL
from harness.engine.llm import LLMClient
from harness.tools.registry import ToolRegistry


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_SHARED_SCRIPTS_DIR = _BACKEND_DIR / "workflows" / "_shared" / "scripts"


def _dir_has_real_files(d: Path) -> bool:
    """Return True iff directory exists and contains at least one non-dotfile."""
    if not d.exists() or not d.is_dir():
        return False
    return any(not p.name.startswith(".") for p in d.iterdir())


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

    @staticmethod
    def _display_name(upstream_name: str) -> str:
        """Rewrite _judge_X → X so downstream agents see the target name."""
        if upstream_name.startswith("_judge_"):
            return upstream_name[len("_judge_"):]
        return upstream_name

    def build_node_prompt(
        self,
        inputs: dict,
        upstream_outputs: dict,
        workflow_dir: Path | None = None,
        critique: str | None = None,
    ) -> str:
        """Build the context portion of a node's prompt.

        Generates ## Task (from inputs), ## Output from X (from upstream),
        ## Previous judgment (when critique is provided — judge returned fail
        and the target agent is retrying), and (when workflow_dir is given and
        its scripts/ or the shared scripts/ pool is non-empty) an
        ## Available scripts section pointing the agent at absolute script paths.
        This is passed as the user message; the agent's md_prompt is the system prompt.
        """
        parts = []

        if inputs:
            parts.append(f"## Task\n{json.dumps(inputs, indent=2, ensure_ascii=False)}")

        for name, output in upstream_outputs.items():
            display = self._display_name(name)
            if isinstance(output, BaseModel):
                parts.append(
                    f"## Output from {display}\n{output.model_dump_json(indent=2)}"
                )
            else:
                parts.append(f"## Output from {display}\n{output}")

        if critique is not None:
            parts.append(f"## Previous judgment\n{critique}")

        if workflow_dir is not None:
            private_scripts = Path(workflow_dir) / "scripts"
            shared_scripts = _SHARED_SCRIPTS_DIR
            has_private = _dir_has_real_files(private_scripts)
            has_shared = _dir_has_real_files(shared_scripts)
            if has_private or has_shared:
                lines = ["## Available scripts (call via bash tool)"]
                if has_private:
                    lines.append(f"- Private (workflow-specific): {private_scripts}")
                if has_shared:
                    lines.append(f"- Shared (cross-workflow):     {shared_scripts}")
                parts.append("\n".join(lines))

        return "\n\n".join(parts)
