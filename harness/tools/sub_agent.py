from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent as PydanticAgent, RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.constants import DEFAULT_MODEL
from harness.tools.registry import ToolFactory

if TYPE_CHECKING:
    from harness.tools.registry import ToolRegistry


class SubAgentToolFactory(ToolFactory):
    """sub_agent 工具 — 委托子任务给临时 agent，最多一层，不可嵌套"""

    name = "sub_agent"
    description = (
        "Launch a sub-agent to handle a specific task. "
        "Provide the task description and any relevant context. "
        "The sub-agent executes independently and returns its result. "
        "Sub-agents cannot spawn further sub-agents. "
        "Use for focused work that benefits from dedicated attention."
    )

    def __init__(
        self,
        registry: ToolRegistry,
        model: str | None = None,
        max_depth: int = 1,
    ):
        self.registry = registry
        self.model = model or DEFAULT_MODEL
        self.max_depth = max_depth

    def create(self, depth: int = 0) -> PydanticAITool:
        registry = self.registry
        model = self.model
        max_depth = self.max_depth

        async def sub_agent(ctx: RunContext, task: str) -> str:
            if depth >= max_depth:
                return "Error: maximum sub-agent depth reached"

            # Create temporary agent WITHOUT sub_agent tool (physical nesting prevention)
            exclude = ["sub_agent"]
            resolved_tools = registry.resolve(None, exclude=exclude)

            child_deps = AgentDeps(
                workdir=ctx.deps.workdir,
                agent_name="sub_agent",
                depth=depth + 1,
            )

            child = PydanticAgent(
                model=model,
                system_prompt="You are a sub-agent. Complete the assigned task concisely.",
                tools=resolved_tools,
                output_type=str,
                defer_model_check=True,
                deps_type=AgentDeps,
            )

            result = await child.run(task, deps=child_deps)
            return result.output

        return PydanticAITool(sub_agent, takes_ctx=True)
