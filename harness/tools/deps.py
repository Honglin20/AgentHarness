from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from harness.engine.token_aggregator import TokenAggregator


class AgentDeps(BaseModel):
    """通过 RunContext.deps 传递给工具的运行时上下文"""
    workdir: str = "."
    agent_name: str = ""
    depth: int = 0
    workflow_id: str = ""
    node_id: str = ""
    token_aggregator: Any = None  # Optional TokenAggregator — excluded from JSON

    model_config = {"extra": "allow"}
