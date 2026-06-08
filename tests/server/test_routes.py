"""Tests for REST API routes."""

import pytest

from server.schemas import AgentDef, AgentInfo, AgentSnapshot, ToolInfo
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

    # Monkeypatch _WORKFLOWS_DIR at the canonical source (harness.api) so
    # _helpers._validate_workflow_dir resolves under tmp_path.
    import harness.core.workflow as harness_api
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    monkeypatch.setattr(harness_api, "_WORKFLOWS_DIR", workflows_dir)
    # Keep the routes-level re-export in sync for backward-compat.
    monkeypatch.setattr(routes, "_WORKFLOWS_DIR", workflows_dir)

    # Monkeypatch _SHARED_AGENTS_DIR at the canonical source (harness.compiler.md_parser)
    # because the agents router reads it from there.
    import harness.compiler.md_parser as md_parser
    import server.routers.agents as agents_router
    shared_dir = tmp_path / "_shared_agents"
    shared_dir.mkdir()
    monkeypatch.setattr(md_parser, "_SHARED_AGENTS_DIR", shared_dir)
    monkeypatch.setattr(agents_router, "_SHARED_AGENTS_DIR", shared_dir)
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


def test_agents_snapshot_includes_conditional_edges():
    """_build_agents_snapshot captures on_pass/on_fail/eval from agent defs."""
    from harness.api import Agent, Workflow
    from server.runner import _build_agents_snapshot

    agents = [
        Agent(name="a", after=[]),
        Agent(name="b", after=["a"], on_pass="c", on_fail="d"),
        Agent(name="c", after=[]),
        Agent(name="d", after=[], eval=True),
    ]
    wf = Workflow(name="test", agents=agents)
    snapshot = _build_agents_snapshot(wf)

    by_name = {s["name"]: s for s in snapshot}
    assert by_name["a"].get("on_pass") is None
    assert by_name["a"].get("on_fail") is None
    assert by_name["b"]["on_pass"] == "c"
    assert by_name["b"]["on_fail"] == "d"
    assert by_name["d"].get("eval") is True


def test_agent_snapshot_schema_accepts_new_fields():
    """AgentSnapshot model accepts on_pass/on_fail/eval."""
    snap = AgentSnapshot(
        name="b",
        after=["a"],
        on_pass="c",
        on_fail="d",
        eval=True,
    )
    assert snap.on_pass == "c"
    assert snap.on_fail == "d"
    assert snap.eval is True


@pytest.mark.asyncio
async def test_list_tools():
    """list_tools() returns registered tools from the catalog."""
    from starlette.requests import Request
    from harness.tools.catalog import ToolCatalogService
    from harness.tools.defaults import default_tool_registry

    # Build a catalog with just built-in tools (no MCP)
    catalog = ToolCatalogService()
    reg = default_tool_registry()
    catalog._registry = reg
    catalog._catalog = reg.get_tool_catalog()

    class FakeState:
        tool_catalog = catalog
    class FakeApp:
        state = FakeState()

    scope = {"type": "http", "headers": [], "query_string": b"", "path": "/", "app": FakeApp()}
    fake_request = Request(scope)

    from server.routes import list_tools
    tools = await list_tools(fake_request)

    tool_names = [t["name"] for t in tools]
    assert "bash" in tool_names
    assert "sub_agent" in tool_names