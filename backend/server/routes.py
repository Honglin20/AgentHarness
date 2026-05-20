"""REST API routes."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from harness.api import Agent, Workflow
from harness.compiler.md_parser import parse_agent_md
from harness.compiler.dag_builder import build_dag
from harness.engine.macro_graph import MacroGraphBuilder
from harness.tools.registry import ToolRegistry
from server.schemas import (
    AgentDef,
    AgentInfo,
    CreateWorkflowRequest,
    CreateWorkflowResponse,
    HealthResponse,
    ToolInfo,
    WorkflowStatusResponse,
)

router = APIRouter()

# In-memory storage (production: use database)
_workflows: dict[str, dict] = {}  # workflow_id -> {workflow, status, result}
_dag_cache: dict[str, dict] = {}  # workflow_id -> dag structure


def get_event_bus():
    """Dependency to get EventBus from app state."""
    from server.event_bus import get_event_bus
    return get_event_bus()


@router.get("/health")
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse()


@router.post("/config")
async def set_config(request: Request) -> dict:
    """Set API key / model at runtime. Optionally persist to .env."""
    from harness.config import configure

    body = await request.json()
    return configure(
        api_key=body.get("api_key"),
        model=body.get("model"),
        persist=body.get("persist", True),
    )


@router.get("/config")
async def get_config() -> dict:
    """Get current config (key masked)."""
    from harness.config import get_config as gc
    return gc()


@router.get("/agents")
async def list_agents(agents_dir: str = "agents") -> list[AgentInfo]:
    """List all available agents by scanning agents_dir."""
    agents_dir_path = Path(agents_dir)
    if not agents_dir_path.exists():
        return []

    agents = []
    for md_file in agents_dir_path.glob("*.md"):
        try:
            parsed = parse_agent_md(md_file)
            agents.append(AgentInfo(
                name=parsed.name,
                description=parsed.description,
                model=parsed.model,
                retries=parsed.retries,
                tools=parsed.tools or [],
            ))
        except Exception as e:
            # Skip invalid agent files
            continue

    return agents


@router.get("/agents/{name}")
async def get_agent(name: str, agents_dir: str = "agents") -> AgentInfo:
    """Get a specific agent's definition."""
    md_path = Path(agents_dir) / f"{name}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    try:
        parsed = parse_agent_md(md_path)
        return AgentInfo(
            name=parsed.name,
            description=parsed.description,
            model=parsed.model,
            retries=parsed.retries,
            tools=parsed.tools or [],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse agent: {e}")


@router.get("/tools")
async def list_tools() -> list[ToolInfo]:
    """List all registered tools."""
    from harness.tools.defaults import default_tool_registry

    registry = default_tool_registry()
    tool_names = registry.list_tools()

    tools = []
    for name in tool_names:
        # Get description from factory
        factory = registry._factories.get(name)
        desc = factory.description if factory else ""
        tools.append(ToolInfo(name=name, description=desc))

    return tools


@router.post("/charts")
async def chart_render(
    request: Request,
    event_bus = Depends(get_event_bus),
) -> dict:
    """Receive chart payload from render_chart() HTTP fallback and emit via EventBus."""
    body = await request.json()
    node_id = body.get("node_id", "")
    chart = body.get("chart", {})

    event_bus.emit("chart.render", {
        "node_id": node_id,
        "agent_name": node_id,
        "chart": chart,
    })

    return {"status": "ok"}


@router.post("/workflows", response_model=CreateWorkflowResponse)
async def create_workflow(
    request: CreateWorkflowRequest,
    event_bus = Depends(get_event_bus),
) -> CreateWorkflowResponse:
    """Create and start a workflow."""
    workflow_id = str(uuid.uuid4())

    # Convert AgentDef to Agent
    agents = [Agent(name=a.name, after=a.after) for a in request.agents]

    # Create Workflow instance
    workflow = Workflow(
        name=request.name,
        agents=agents,
        agents_dir=request.agents_dir,
        tool_registry=ToolRegistry(),
        event_bus=event_bus,
    )

    # Store workflow
    _workflows[workflow_id] = {
        "workflow": workflow,
        "status": "running",
        "result": None,
    }

    # Build DAG for React Flow
    node_order = build_dag(agents)
    edges: list[list[str]] = []
    for a in agents:
        for dep in a.after:
            edges.append([dep, a.name])
    _dag_cache[workflow_id] = {"nodes": node_order, "edges": edges}

    # Emit workflow.started event (actual execution managed by WorkflowRunner)
    event_bus.emit("workflow.started", {
        "workflow_id": workflow_id,
        "name": workflow.name,
        "inputs": request.inputs,
        "dag": {"nodes": node_order, "edges": edges},  # Include DAG structure for frontend
    })

    # Submit to runner
    from server.runner import get_runner
    runner = get_runner()
    await runner.submit(workflow_id, workflow, request.inputs, event_bus)

    return CreateWorkflowResponse(
        workflow_id=workflow_id,
        status="running",
        dag={"nodes": node_order, "edges": edges},
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow(workflow_id: str) -> WorkflowStatusResponse:
    """Get workflow status and result."""
    if workflow_id not in _workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = _workflows[workflow_id]
    return WorkflowStatusResponse(
        workflow_id=workflow_id,
        name=data["workflow"].name,
        status=data["status"],
        result=data["result"],
    )


@router.post("/workflows/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str) -> dict:
    """Cancel a running workflow."""
    if workflow_id not in _workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    from server.runner import get_runner
    runner = get_runner()

    cancelled = await runner.cancel(workflow_id)

    if cancelled:
        _workflows[workflow_id]["status"] = "cancelled"

    return {"status": "cancelled"}


@router.get("/workflows/{workflow_id}/dag")
async def get_workflow_dag(workflow_id: str) -> dict:
    """Get DAG structure for React Flow."""
    if workflow_id not in _dag_cache:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return _dag_cache[workflow_id]


@router.get("/workflows/{workflow_id}/trace")
async def get_workflow_trace(workflow_id: str) -> dict:
    """Get execution trace."""
    if workflow_id not in _workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = _workflows[workflow_id]
    result = data["result"]

    if result is None:
        return {"workflow_id": workflow_id, "trace": []}

    return {
        "workflow_id": workflow_id,
        "trace": result.get("trace", []),
    }