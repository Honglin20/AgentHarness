"""Tests for REST API routes."""

import pytest

from server.schemas import AgentDef, AgentInfo, ToolInfo
from harness.api import WorkflowResult


def test_agent_def_validation():
    """AgentDef validates correctly."""
    agent = AgentDef(name="analyzer", after=[])
    assert agent.name == "analyzer"
    assert agent.after == []

    agent2 = AgentDef(name="planner", after=["analyzer"])
    assert agent2.after == ["analyzer"]


def test_agent_info():
    """AgentInfo model works correctly."""
    info = AgentInfo(
        name="analyzer",
        description="Code analysis expert",
        model="gpt-4",
        retries=3,
        tools=["bash", "read_file"],
    )
    assert info.name == "analyzer"
    assert info.model == "gpt-4"
    assert info.tools == ["bash", "read_file"]


def test_tool_info():
    """ToolInfo model works correctly."""
    info = ToolInfo(name="bash", description="Execute bash commands")
    assert info.name == "bash"
    assert info.description == "Execute bash commands"


@pytest.mark.asyncio
async def test_list_agents_from_fixtures(tmp_path):
    """list_agents() scans fixtures directory."""
    from server.routes import list_agents

    # Create test agents dir
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    (agents_dir / "test1.md").write_text("""
---
name: test1
model: gpt-4
---
This is a test agent.
""")

    (agents_dir / "test2.md").write_text("invalid content")

    agents = await list_agents(agents_dir=str(agents_dir))

    assert len(agents) == 1
    assert agents[0].name == "test1"
    assert agents[0].model == "gpt-4"


@pytest.mark.asyncio
async def test_list_tools():
    """list_tools() returns registered tools."""
    from server.routes import list_tools

    tools = await list_tools()

    # Should have at least bash and sub_agent from default registry
    tool_names = [t.name for t in tools]
    assert "bash" in tool_names
    assert "sub_agent" in tool_names