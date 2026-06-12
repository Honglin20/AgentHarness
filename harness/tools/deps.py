from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from harness.engine.token_aggregator import TokenAggregator


class AgentDeps(BaseModel):
    """通过 RunContext.deps 传递给工具的运行时上下文"""
    model_config = ConfigDict(
        extra="allow",
        # TokenAggregator is a plain (non-pydantic) class — pydantic v2 needs
        # this to accept arbitrary types as field values.
        arbitrary_types_allowed=True,
    )

    workdir: str = "."
    agent_name: str = ""
    depth: int = 0
    workflow_id: str = ""
    node_id: str = ""
    # Loop iteration counter for this node invocation (1-indexed). Injected
    # by node_factory at deps construction time. Consumed by todo tool to
    # stamp StepEntry.iteration. Plan F.
    iteration: int = 1
    # Runtime-only: never serialized (carries mutable aggregator state that
    # makes no sense to persist or send over the wire).
    token_aggregator: TokenAggregator | None = Field(default=None, exclude=True)
