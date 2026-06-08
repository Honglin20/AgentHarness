"""Public Pydantic data models for the harness public API.

Kept separate from ``Agent``/``Workflow`` so callers that only need the
result shape can import the models without pulling in the full
workflow/MCP stack.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    """Default ``result_type`` for agents that don't declare one.

    The agent's final conclusion goes in ``summary``; reasoning and
    intermediate observations go in ``details``.
    """

    summary: str = Field(
        description="Your final conclusion or answer. Be concise and direct."
    )
    details: str | None = Field(
        default=None,
        description=(
            "Your reasoning process, analysis steps, and key observations. "
            "Show your chain of thought here."
        ),
    )


class TokenUsage(BaseModel):
    """Per-node or per-run token accounting."""

    input: int
    output: int
    total: int


class NodeTrace(BaseModel):
    """One row in the per-agent execution trace returned by ``Workflow.run``."""

    agent_name: str
    status: Literal["success", "failed", "skipped"]
    duration_ms: int
    error: str | None = None
    token_usage: TokenUsage | None = None


class WorkflowResult(BaseModel):
    """The return value of ``Workflow.run()`` / ``Workflow.arun()``."""

    outputs: dict[str, Any]
    errors: dict[str, str]
    trace: list[NodeTrace]
    interrupted: bool = False
    interrupt_value: Any | None = None
