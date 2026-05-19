"""Phase 2 integration: ToolRegistry + sub_agent + default tools + Workflow"""
from unittest.mock import patch, MagicMock

from harness.api import Agent, Workflow, WorkflowResult
from harness.tools.registry import ToolRegistry
from harness.tools.sub_agent import SubAgentToolFactory
from harness.tools.bash import BashToolFactory
from harness.tools.defaults import default_tool_registry


def test_workflow_with_default_tools():
    """Workflow with default ToolRegistry resolves tools correctly."""
    registry = default_tool_registry()

    agents = [
        Agent("analyzer", after=[]),
        Agent("planner", after=["analyzer"]),
    ]
    # Verify registry resolves
    tools = registry.resolve(None)
    tool_names = [t.name for t in tools]
    assert "sub_agent" in tool_names
    assert "bash" in tool_names


def test_workflow_with_explicit_tools():
    """Agent with explicit tools only gets those tools."""
    registry = default_tool_registry()

    # Explicit tool list
    tools = registry.resolve(["bash"])
    assert len(tools) == 1
    assert tools[0].name == "bash"


def test_workflow_compile_with_tool_registry():
    """Workflow.compile() passes ToolRegistry to MacroGraphBuilder."""
    registry = default_tool_registry()

    agents = [
        Agent("analyzer", after=[]),
    ]

    # Patch at the source module level
    with patch("harness.engine.macro_graph.MacroGraphBuilder") as MockBuilder, \
         patch("harness.tools.defaults.setup_default_mcp") as mock_mcp:
        mock_mcp.return_value = []  # No MCP bridges
        mock_graph = MagicMock()
        mock_builder_instance = MockBuilder.return_value
        mock_builder_instance.build.return_value = mock_graph
        mock_graph.compile.return_value = MagicMock()

        wf = Workflow("test_wf", agents=agents, agents_dir="tests/compiler/fixtures", tool_registry=registry)
        wf.compile()

        MockBuilder.assert_called_once_with(tool_registry=registry)


def test_workflow_exclude_sub_agent_for_child():
    """Sub-agent depth=1 should not have sub_agent tool."""
    registry = default_tool_registry()

    # Parent agent gets all tools
    all_tools = registry.resolve(None)
    tool_names = [t.name for t in all_tools]
    assert "sub_agent" in tool_names

    # Child agent (exclude sub_agent)
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

    agents = [
        Agent("analyzer", after=[]),
    ]
    wf = Workflow("test_wf", agents=agents, agents_dir="tests/compiler/fixtures", tool_registry=registry)

    with patch("pydantic_ai.Agent.run_sync") as mock_run_sync:
        mock_result = MagicMock()
        mock_result.output = "分析完成"
        mock_run_sync.return_value = mock_result

        # Need to bypass compile()'s MCP setup
        with patch("harness.tools.defaults.setup_default_mcp", return_value=[]):
            result = wf.run({"task": "test"})

        assert isinstance(result, WorkflowResult)
        assert "analyzer" in result.outputs
