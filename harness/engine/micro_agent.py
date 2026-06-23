from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel
from pydantic_ai import Agent as PydanticAgent

from harness.api import AgentResult
from harness.tools.deps import AgentDeps
from harness.constants import DEFAULT_MODEL
from harness.engine.llm import LLMClient
from harness.engine.step_gate import step_gate_validator
from harness.tools.registry import ToolRegistry


from harness.paths import get_shared_scripts_dir
from harness.prompts.runtime import runtime_status

_SHARED_SCRIPTS_DIR = get_shared_scripts_dir()


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

        effective_result_type = result_type if result_type is not None else AgentResult
        client = LLMClient(model=agent_model) if model else LLMClient()
        # retries as dict: tools budget from caller. output budget=2 gives the
        # model a second chance after pydantic-ai feeds back the ValidationError
        # (or after step_gate raises ModelRetry). 1 was too tight — agents that
        # finished real work but emitted markdown instead of JSON had no room
        # to correct, and the failure cascaded into downstream skips. See
        # 2026-06-17 adapter_generator incident.
        retries_dict = {"tools": retries, "output": 2}
        agent = client.agent(
            system_prompt=prompt,
            output_type=effective_result_type,
            retries=retries_dict,
            tools=resolved_tools,
            deps_type=AgentDeps,
        )

        # Inject step completion gate as output_validator. On violation raises
        # ModelRetry → pydantic-ai continues iter() with retry prompt in
        # message_history (does NOT restart; preserves prior tool calls).
        @agent.output_validator
        async def _step_gate(ctx, data):
            return await step_gate_validator(ctx, data)

        # Register the dynamic runtime-status system prompt (TASK 4). pydantic-ai
        # calls runtime_status BEFORE EVERY model request and REPLACES the prior
        # turn's status in place (dynamic_ref) rather than appending — so the
        # model always sees current todo progress + any recent tool failure,
        # without the accumulating-reminder problem of the old
        # TodoReminderTracker. Reads ctx.deps (AgentDeps), which tools mutate
        # to surface failures. See harness/prompts/runtime.py.
        agent.system_prompt(dynamic=True)(runtime_status)

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
            task_text = inputs.get("task")
            if task_text and isinstance(task_text, str):
                parts.append(f"## Task\n{task_text}")
                context_keys = {k: v for k, v in inputs.items() if k != "task"}
                if context_keys:
                    parts.append(f"## Context\n{json.dumps(context_keys, indent=2, ensure_ascii=False)}")
            else:
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
