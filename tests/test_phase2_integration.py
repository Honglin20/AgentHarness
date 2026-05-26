"""Phase 2 integration: ToolRegistry + sub_agent + default tools + Workflow"""
from unittest.mock import AsyncMock, MagicMock, patch

from harness.api import Agent, Workflow, WorkflowResult
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory
from harness.tools.bash import BashToolFactory
from harness.tools.defaults import default_tool_registry


def test_workflow_with_default_tools():
    """Workflow with default ToolRegistry resolves tools correctly."""
    registry = default_tool_registry()
    tools = registry.resolve(None)
    tool_names = [t.name for t in tools]
    assert "sub_agent" in tool_names
    assert "bash" in tool_names


def test_workflow_with_explicit_tools():
    """Agent with explicit tools only gets those tools."""
    registry = default_tool_registry()
    tools = registry.resolve(["bash"])
    assert len(tools) == 1
    assert tools[0].name == "bash"


def test_workflow_compile_with_tool_registry():
    """Workflow.compile() passes ToolRegistry to MacroGraphBuilder."""
    registry = default_tool_registry()
    agents = [Agent("analyzer", after=[])]

    wf = Workflow("test_wf", agents=agents, agents_dir="tests/compiler/fixtures", tool_registry=registry)
    # Just verify it compiles without error
    graph = wf.compile()
    assert graph is not None


def test_workflow_exclude_sub_agent_for_child():
    """Sub-agent depth=1 should not have sub_agent tool."""
    registry = default_tool_registry()

    all_tools = registry.resolve(None)
    assert "sub_agent" in [t.name for t in all_tools]

    child_tools = registry.resolve(None, exclude=["sub_agent"])
    child_tool_names = [t.name for t in child_tools]
    assert "sub_agent" not in child_tool_names
    assert "bash" in child_tool_names


def test_workflow_accepts_mcp_servers():
    """Workflow accepts mcp_servers parameter."""
    from harness.tools.mcp_bridge import McpServerConfig

    config = McpServerConfig(name="custom", command="npx", args=["-y", "some-server"])
    wf = Workflow("test", agents=[], mcp_servers=[config])
    assert len(wf.mcp_servers) == 1
    assert wf.mcp_servers[0].name == "custom"


def test_workflow_run_with_tools_mocked():
    """Workflow.run() with tool registry and mocked LLM."""
    registry = default_tool_registry()
    agents = [Agent("analyzer", after=[])]
    wf = Workflow("test_wf", agents=agents, agents_dir="tests/compiler/fixtures", tool_registry=registry)

    with patch("pydantic_ai.Agent.run", new_callable=AsyncMock) as mock_run:
        mock_result = MagicMock()
        mock_result.output = "分析完成"
        mock_run.return_value = mock_result

        with patch.object(wf, "setup", new_callable=AsyncMock), \
             patch.object(wf, "cleanup", new_callable=AsyncMock):
            result = wf.run({"task": "test"})

        assert isinstance(result, WorkflowResult)
        assert "analyzer" in result.outputs


def test_skipped_status_detection():
    """Agent not in outputs and not in errors → status='skipped'."""
    wf = Workflow("test", agents=[
        Agent("a", after=[]),
        Agent("b", after=["a"]),
    ])
    final_state = {
        "outputs": {"a": "result"},
        "errors": {},
        "metadata": {"a": {"duration_ms": 100}},
    }
    result = wf._build_result(final_state)
    assert result.trace[0].status == "success"
    assert result.trace[1].status == "skipped"
