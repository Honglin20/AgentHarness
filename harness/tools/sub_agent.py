from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.constants import DEFAULT_MODEL
from harness.engine.llm import LLMClient
from harness.tools.registry import ToolFactory

if TYPE_CHECKING:
    from harness.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Tools that require event_bus / user interaction — not usable by sub-agents.
_EXCLUDE_FROM_CHILD = {"sub_agent", "ask_user"}


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

            # Resolve safe tools: exclude sub_agent + context-dependent tools
            exclude = list(_EXCLUDE_FROM_CHILD)
            resolved_tools = registry.resolve(None, exclude=exclude)

            child_deps = AgentDeps(
                workdir=ctx.deps.workdir,
                agent_name="sub_agent",
                depth=depth + 1,
            )

            # Propagate parent's token aggregator so sub-agent usage is tracked
            parent_agg = getattr(ctx.deps, "token_aggregator", None)
            parent_name = getattr(ctx.deps, "agent_name", "unknown")

            client = LLMClient(model=model) if model else LLMClient()
            try:
                child = client.agent(
                    system_prompt="You are a sub-agent. Complete the assigned task concisely.",
                    output_type=str,
                    tools=resolved_tools,
                    deps_type=AgentDeps,
                )

                result = await child.run(task, deps=child_deps)

                # Record sub-agent token usage into parent's aggregator
                if parent_agg is not None:
                    usage_obj = getattr(result, "usage", None)
                    if usage_obj is not None:
                        sub_key = f"{parent_name}.sub_agent"
                        parent_agg.record(
                            sub_key,
                            input_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
                            output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
                            cache_hit_tokens=getattr(usage_obj, "prompt_cache_hit_tokens", 0) or 0,
                            reasoning_tokens=getattr(usage_obj, "reasoning_tokens", 0) or 0,
                        )

                return result.output
            except Exception as e:
                logger.warning("sub_agent failed: %s: %s", type(e).__name__, e)
                return f"Error: sub-agent failed — {type(e).__name__}: {e}"
            finally:
                await client.aclose()

        return PydanticAITool(self._wrap_fn(sub_agent, self.name), takes_ctx=True)
