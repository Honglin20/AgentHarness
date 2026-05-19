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
        """Compile the workflow into a LangGraph StateGraph."""
        from harness.engine.macro_graph import MacroGraphBuilder

        builder = MacroGraphBuilder()
        graph = builder.build(self)
        self._compiled = graph.compile()
        return self._compiled

    def run(self, inputs: dict) -> WorkflowResult:
        """Run the workflow synchronously."""
        if self._compiled is None:
            self.compile()

        initial_state = {
            "inputs": inputs,
            "outputs": {},
            "errors": {},
            "metadata": {},
        }

        final_state = self._compiled.invoke(initial_state)
        return self._build_result(final_state)

    async def arun(self, inputs: dict) -> WorkflowResult:
        """Run the workflow asynchronously."""
        if self._compiled is None:
            self.compile()

        initial_state = {
            "inputs": inputs,
            "outputs": {},
            "errors": {},
            "metadata": {},
        }

        final_state = await self._compiled.ainvoke(initial_state)
        return self._build_result(final_state)

    def _build_result(self, final_state: dict) -> WorkflowResult:
        """Construct WorkflowResult from final LangGraph state."""
        outputs = final_state.get("outputs", {})
        errors = final_state.get("errors", {})
        metadata = final_state.get("metadata", {})

        trace = []
        for agent in self.agents:
            agent_meta = metadata.get(agent.name, {})
            duration_ms = agent_meta.get("duration_ms", 0) if isinstance(agent_meta, dict) else 0
            status = "failed" if agent.name in errors else "success"
            error_msg = errors.get(agent.name)

            trace.append(NodeTrace(
                agent_name=agent.name,
                status=status,
                duration_ms=duration_ms,
                error=error_msg,
            ))

        return WorkflowResult(outputs=outputs, errors=errors, trace=trace)
