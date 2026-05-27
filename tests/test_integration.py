from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from harness.api import Agent, Workflow, WorkflowResult


FIXTURES_DIR = str(Path(__file__).parent / "compiler" / "fixtures")


def test_workflow_compile_returns_compiled_graph():
    """Workflow.compile() returns a compiled LangGraph graph."""
    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
    ]
    wf = Workflow("test_wf", agents=agents, agents_dir=FIXTURES_DIR)

    compiled = wf.compile()
    assert compiled is not None


def test_workflow_run_with_mocked_llm():
    """Workflow.run() returns a WorkflowResult with correct structure."""
    from harness.api import AgentResult
    from pydantic_graph import End

    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
    ]
    wf = Workflow("test_wf", agents=agents, agents_dir=FIXTURES_DIR)

    mock_output = AgentResult(summary="mock output")

    fake_agent_run = MagicMock()
    fake_agent_run.next_node = End(data=mock_output)
    fake_agent_run.result.output = mock_output
    fake_agent_run.usage = MagicMock()

    fake_iter_ctx = MagicMock()
    fake_iter_ctx.__aenter__ = AsyncMock(return_value=fake_agent_run)
    fake_iter_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("pydantic_ai.Agent.iter", return_value=fake_iter_ctx):
        # Patch setup/cleanup to skip MCP
        with patch.object(wf, "setup", new_callable=AsyncMock), \
             patch.object(wf, "cleanup", new_callable=AsyncMock):
            wf.compile()
            result = wf.run({"task": "test"})

        assert isinstance(result, WorkflowResult)
        assert "analyzer" in result.outputs
        assert "planner" in result.outputs
        assert result.outputs["analyzer"] == mock_output
        assert result.outputs["planner"] == mock_output
        assert len(result.trace) == 2
        assert result.trace[0].agent_name == "analyzer"
        assert result.trace[1].agent_name == "planner"
