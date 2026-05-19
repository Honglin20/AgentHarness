from __future__ import annotations

from typing import Any, Literal, Type

from pydantic import BaseModel


class Agent:
    """Declarative agent definition."""

    def __init__(
        self,
        name: str,
        after: list[str] | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        retries: int = 3,
        result_type: Type[BaseModel] | None = None,
    ):
        self.name = name
        self.after = after or []
        self.tools = tools
        self.model = model
        self.retries = retries
        self.result_type = result_type


class NodeTrace(BaseModel):
    agent_name: str
    status: Literal["success", "failed", "skipped"]
    duration_ms: int
    error: str | None = None


class WorkflowResult(BaseModel):
    outputs: dict[str, Any]
    errors: dict[str, str]
    trace: list[NodeTrace]


class Workflow:
    """Declarative workflow definition."""

    def __init__(
        self,
        name: str,
        agents: list[Agent],
        agents_dir: str = "agents",
    ):
        self.name = name
        self.agents = agents
        self.agents_dir = agents_dir
        self._compiled = None

    def compile(self):
        raise NotImplementedError

    def run(self, inputs: dict) -> WorkflowResult:
        raise NotImplementedError

    async def arun(self, inputs: dict) -> WorkflowResult:
        raise NotImplementedError
