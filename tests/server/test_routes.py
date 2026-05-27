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
async def test_list_agents_from_fixtures(tmp_path, monkeypatch):
    """list_agents() scans workflow directory with private-first, shared-fallback."""
    from server.routes import list_agents
    import server.routes as routes

    # Monkeypatch _WORKFLOWS_DIR so _validate_workflow_dir resolves under tmp_path
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    monkeypatch.setattr(routes, "_WORKFLOWS_DIR", workflows_dir)

    # Monkeypatch _SHARED_AGENTS_DIR to empty dir to isolate test
    shared_dir = tmp_path / "_shared_agents"
    shared_dir.mkdir()
    monkeypatch.setattr(routes, "_SHARED_AGENTS_DIR", shared_dir)

    # Create a workflow with a private agent
    wf_dir = workflows_dir / "test_wf"
    agents_dir = wf_dir / "agents"
    agents_dir.mkdir(parents=True)

    (agents_dir / "test1.md").write_text("""---
name: test1
model: gpt-4
---
This is a test agent.
""")

    (agents_dir / "test2.md").write_text("invalid content")

    from starlette.testclient import TestClient
    from starlette.requests import Request

    # Create a minimal fake Request since this is a FastAPI dependency
    scope = {"type": "http", "headers": [], "query_string": b"", "path": "/"}
    fake_request = Request(scope)

    agents = await list_agents(workflow="test_wf", request=fake_request)

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