"""Tests for the workflow directory layout — agent MD read/write + workflow creation."""

from pathlib import Path

import pytest
from starlette.requests import Request


def _make_fake_request() -> Request:
    """Create a minimal fake Request for route functions that need it."""
    scope = {"type": "http", "headers": [], "query_string": b"", "path": "/"}
    return Request(scope)


@pytest.mark.asyncio
async def test_get_agent_md_workflow_query_private(tmp_path, monkeypatch):
    """GET /agents/{name}/md?workflow=... returns private MD when present."""
    from server import routes
    import harness.core.workflow as harness_api
    import harness.compiler.md_parser as md_parser
    import server.routers.agents as agents_router

    wf_root = tmp_path / "workflows"
    wf_dir = wf_root / "demo"
    (wf_dir / "agents").mkdir(parents=True)
    (wf_dir / "agents" / "a.md").write_text("---\nname: a\n---\nprivate body")
    shared = wf_root / "_shared" / "agents"
    shared.mkdir(parents=True)
    (shared / "a.md").write_text("---\nname: a\n---\nshared body")

    monkeypatch.setattr(harness_api, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(routes, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(md_parser, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(agents_router, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(routes, "_SHARED_AGENTS_DIR", shared)

    result = await routes.get_agent_md(name="a", workflow="demo", request=_make_fake_request())
    assert "private body" in result["md_content"]
    assert result["source"] == "private"
    assert result["workflow"] == "demo"


@pytest.mark.asyncio
async def test_get_agent_md_workflow_fallback_shared(tmp_path, monkeypatch):
    """When the private MD is missing, falls back to the shared pool."""
    from server import routes
    import harness.core.workflow as harness_api
    import harness.compiler.md_parser as md_parser
    import server.routers.agents as agents_router

    wf_root = tmp_path / "workflows"
    wf_dir = wf_root / "demo"
    (wf_dir / "agents").mkdir(parents=True)
    shared = wf_root / "_shared" / "agents"
    shared.mkdir(parents=True)
    (shared / "runner.md").write_text("---\nname: runner\n---\nrunner body")

    monkeypatch.setattr(harness_api, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(routes, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(md_parser, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(agents_router, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(routes, "_SHARED_AGENTS_DIR", shared)

    result = await routes.get_agent_md(name="runner", workflow="demo", request=_make_fake_request())
    assert "runner body" in result["md_content"]
    assert result["source"] == "shared"


@pytest.mark.asyncio
async def test_get_agent_md_workflow_not_found_404(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from server import routes
    import harness.core.workflow as harness_api
    import harness.compiler.md_parser as md_parser
    import server.routers.agents as agents_router

    wf_root = tmp_path / "workflows"
    wf_dir = wf_root / "demo"
    (wf_dir / "agents").mkdir(parents=True)
    shared = wf_root / "_shared" / "agents"
    shared.mkdir(parents=True)

    monkeypatch.setattr(harness_api, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(routes, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(md_parser, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(agents_router, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(routes, "_SHARED_AGENTS_DIR", shared)

    with pytest.raises(HTTPException) as exc:
        await routes.get_agent_md(name="ghost", workflow="demo", request=_make_fake_request())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_put_agent_md_target_private(tmp_path, monkeypatch):
    """PUT with target='private' writes to workflows/<wf>/agents/<name>.md."""
    from server import routes
    import harness.core.workflow as harness_api
    import harness.compiler.md_parser as md_parser
    import server.routers.agents as agents_router

    wf_root = tmp_path / "workflows"
    wf_dir = wf_root / "demo"
    (wf_dir / "agents").mkdir(parents=True)
    shared = wf_root / "_shared" / "agents"
    shared.mkdir(parents=True)

    monkeypatch.setattr(harness_api, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(routes, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(md_parser, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(agents_router, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(routes, "_SHARED_AGENTS_DIR", shared)

    from server.schemas import UpdateAgentMdRequest

    body = UpdateAgentMdRequest(
        workflow="demo",
        target="private",
        md_content="---\nname: writer\n---\nbody",
    )
    result = await routes.update_agent_md(name="writer", body=body, request=_make_fake_request())
    assert result["status"] == "ok"
    assert (wf_dir / "agents" / "writer.md").exists()


@pytest.mark.asyncio
async def test_put_agent_md_target_shared(tmp_path, monkeypatch):
    """PUT with target='shared' writes to workflows/_shared/agents/<name>.md."""
    from server import routes
    import harness.core.workflow as harness_api
    import harness.compiler.md_parser as md_parser
    import server.routers.agents as agents_router

    wf_root = tmp_path / "workflows"
    wf_dir = wf_root / "demo"
    (wf_dir / "agents").mkdir(parents=True)
    shared = wf_root / "_shared" / "agents"
    shared.mkdir(parents=True)

    monkeypatch.setattr(harness_api, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(routes, "_WORKFLOWS_DIR", wf_root)
    monkeypatch.setattr(md_parser, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(agents_router, "_SHARED_AGENTS_DIR", shared)
    monkeypatch.setattr(routes, "_SHARED_AGENTS_DIR", shared)

    from server.schemas import UpdateAgentMdRequest

    body = UpdateAgentMdRequest(
        workflow="demo",
        target="shared",
        md_content="---\nname: helper\n---\nbody",
    )
    result = await routes.update_agent_md(name="helper", body=body, request=_make_fake_request())
    assert result["status"] == "ok"
    assert (shared / "helper.md").exists()


def test_list_definitions_skips_shared(tmp_path, monkeypatch):
    """Workflow.list_saved() skips the _shared/ directory."""
    import harness.core.workflow as api

    monkeypatch.setattr(api, "_WORKFLOWS_DIR", tmp_path)

    from harness.registry import configure_registry, get_registry
    old_reg = get_registry()
    monkeypatch.setattr("harness.registry._global_registry", old_reg)
    configure_registry(tmp_path)

    # Create one real workflow and a _shared dir.
    (tmp_path / "demo" / "agents").mkdir(parents=True)
    (tmp_path / "demo" / "scripts").mkdir()
    (tmp_path / "demo" / "workflow.json").write_text(
        '{"name": "demo", "agents": [{"name": "a", "after": []}]}'
    )
    (tmp_path / "_shared" / "agents").mkdir(parents=True)
    # _shared has no workflow.json but ensure presence of dir doesn't cause issues
    defs = api.Workflow.list_saved()
    # Only check non-builtin resources (builtin demo_pipeline comes from registry)
    assert [d["name"] for d in defs if d.get("scope") != "builtin"] == ["demo"]


def test_validate_workflow_dir_rejects_traversal():
    from fastapi import HTTPException
    from server.routes import _validate_workflow_dir

    with pytest.raises(HTTPException):
        _validate_workflow_dir("../escape")
    with pytest.raises(HTTPException):
        _validate_workflow_dir(".hidden")
