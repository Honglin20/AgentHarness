"""Tool catalog endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request

from harness.extensions.bus import Bus
from server.dependencies import (
    get_event_bus_dep,
    get_repository_dep,
)
from server.repository import WorkflowRepository
from server.schemas import ChartRenderRequest

router = APIRouter()


@router.get("/tools")
async def list_tools(request: Request) -> list[dict]:
    """List all available tools (built-in + MCP) with source and description."""
    catalog = getattr(request.app.state, "tool_catalog", None)
    if catalog is None:
        return []
    return [entry.model_dump() for entry in catalog.get_catalog()]


@router.post("/tools/refresh")
async def refresh_tools(request: Request) -> dict:
    """Force-refresh the tool catalog by reconnecting MCP servers."""
    catalog = getattr(request.app.state, "tool_catalog", None)
    if catalog is None:
        return {"status": "error", "detail": "Tool catalog not initialized"}
    workdir = request.query_params.get("workdir", ".")
    await catalog.refresh(workdir=workdir)
    return {"status": "ok", "count": len(catalog.get_catalog())}


@router.post("/charts")
async def chart_render(
    body: ChartRenderRequest,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
    event_bus: Bus = Depends(get_event_bus_dep),
) -> dict:
    """Receive chart payload from render_chart() HTTP fallback and emit via EventBus.

    Auth note: this endpoint has two callers:
      1. External (browser → frontend) — must send X-User-Id.
      2. Internal (worker subprocess → server, via HARNESS_SERVER_URL) — has no
         user identity, but is always localhost.

    We allow localhost to bypass auth (standard pattern for internal endpoints),
    and require X-User-Id (or X-API-Key) from any other source.
    """
    client_host = request.client.host if request.client else None
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost")
    has_auth = (
        request.headers.get("X-User-Id")
        or request.headers.get("X-API-Key")
    )
    if not is_localhost and not has_auth:
        raise HTTPException(status_code=401, detail="X-User-Id header required")

    node_id = body.node_id
    chart = body.chart

    event_payload = {
        "node_id": node_id,
        "agent_name": node_id,
        "chart": chart,
    }

    # Try to find the specific workflow whose nodes include this node_id
    for _wid, data in repo.all_running():
        workflow = data.get("workflow")
        if workflow and node_id:
            # Check if this node_id matches any agent in this workflow
            if any(a.name == node_id for a in workflow.agents):
                wf_bus = data.get("event_bus")
                if wf_bus:
                    wf_bus.emit("chart.render", event_payload)
                    return {"status": "ok"}

    # If node_id is empty or no specific match, try the active (last-started) running workflow
    running = list(repo.all_running())
    if running:
        _wid, data = running[-1]
        wf_bus = data.get("event_bus")
        if wf_bus:
            wf_bus.emit("chart.render", event_payload)
            return {"status": "ok"}

    # Fallback: emit on global bus for backwards compat
    event_bus.emit("chart.render", event_payload)

    return {"status": "ok"}
