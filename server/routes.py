"""REST API routes."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from harness.api import Agent, Workflow, _WORKFLOWS_DIR
from harness.compiler.md_parser import (
    AgentNotFoundError,
    _SHARED_AGENTS_DIR,
    parse_agent_md,
    resolve_agent_md,
    write_agent_md,
)
from harness.compiler.dag_builder import build_dag
from harness.engine.macro_graph import MacroGraphBuilder
from harness.tools.registry import ToolRegistry
from server.schemas import (
    AgentDef,
    AgentInfo,
    CreateWorkflowRequest,
    CreateWorkflowResponse,
    HealthResponse,
    RunDetail,
    ToolInfo,
    WorkflowStatusResponse,
)

router = APIRouter()

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ALLOWED_AGENTS_BASE = _BACKEND_DIR.parent  # project root — agents/ must be under here


def _validate_agents_dir(agents_dir: str) -> Path:
    """Ensure agents_dir resolves within the project tree. Prevents path traversal."""
    resolved = (Path(_ALLOWED_AGENTS_BASE) / agents_dir).resolve()
    if not str(resolved).startswith(str(_ALLOWED_AGENTS_BASE.resolve())):
        raise HTTPException(status_code=400, detail="agents_dir escapes allowed directory")
    return resolved


def _validate_workflow_dir(workflow: str) -> Path:
    """Validate a workflow folder name and return its absolute path under workflows/.

    Rejects path traversal. The directory does not need to exist (caller decides).
    """
    if not workflow or "/" in workflow or "\\" in workflow or workflow.startswith("."):
        raise HTTPException(status_code=400, detail="invalid workflow name")
    resolved = (_WORKFLOWS_DIR / workflow).resolve()
    if not str(resolved).startswith(str(_WORKFLOWS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="workflow escapes workflows root")
    return resolved

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
        api_url=body.get("api_url"),
        stop_regen_ttl=body.get("stop_regen_ttl"),
        persist=body.get("persist", True),
    )


@router.get("/config")
async def get_config() -> dict:
    """Get current config (key masked)."""
    from harness.config import get_config as gc
    return gc()


@router.get("/agents")
async def list_agents(
    agents_dir: str = "agents",
    workflow: str | None = None,
) -> list[AgentInfo]:
    """List all available agents.

    Resolution order when ``workflow`` is given:
      1. ``workflows/<workflow>/agents/*.md`` (private)
      2. ``workflows/_shared/agents/*.md`` (shared fallback)
    Otherwise falls back to the legacy ``agents_dir`` scan.
    """
    if workflow is not None:
        wf_dir = _validate_workflow_dir(workflow)
        agents: list[AgentInfo] = []
        seen: set[str] = set()

        # Private agents first
        private_dir = wf_dir / "agents"
        if private_dir.exists():
            for md_file in private_dir.glob("*.md"):
                try:
                    parsed = parse_agent_md(md_file)
                    seen.add(parsed.name)
                    agents.append(AgentInfo(
                        name=parsed.name,
                        description=parsed.description,
                        model=parsed.model,
                        retries=parsed.retries,
                        tools=parsed.tools or [],
                    ))
                except Exception:
                    continue

        # Shared agents (not overridden by private)
        if _SHARED_AGENTS_DIR.exists():
            for md_file in _SHARED_AGENTS_DIR.glob("*.md"):
                try:
                    parsed = parse_agent_md(md_file)
                    if parsed.name not in seen:
                        agents.append(AgentInfo(
                            name=parsed.name,
                            description=parsed.description,
                            model=parsed.model,
                            retries=parsed.retries,
                            tools=parsed.tools or [],
                        ))
                except Exception:
                    continue

        return agents

    # Legacy path
    agents_dir_path = _validate_agents_dir(agents_dir)
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
        except Exception:
            continue

    return agents


@router.get("/agents/{name}")
async def get_agent(
    name: str,
    agents_dir: str = "agents",
    workflow: str | None = None,
) -> AgentInfo:
    """Get a specific agent's definition."""
    if workflow is not None:
        wf_dir = _validate_workflow_dir(workflow)
        try:
            md_path = resolve_agent_md(name, wf_dir)
        except AgentNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
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

    # Legacy path
    agents_dir_path = _validate_agents_dir(agents_dir)
    md_path = agents_dir_path / f"{name}.md"
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


@router.get("/agents/{name}/md")
async def get_agent_md(
    name: str,
    workflow: str | None = None,
    agents_dir: str = "agents",
) -> dict:
    """Get the raw Markdown content of an agent definition.

    Resolution order:
      1. ``workflow`` query (new): use ``resolve_agent_md(name, workflows/<workflow>)``
         which falls back to ``workflows/_shared/agents/`` if not found locally.
      2. ``agents_dir`` query (legacy): direct file at ``<agents_dir>/<name>.md``.
    """
    if workflow is not None:
        wf_dir = _validate_workflow_dir(workflow)
        try:
            md_path = resolve_agent_md(name, wf_dir)
        except AgentNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        # Determine origin (private vs shared) for the client.
        source = "private" if md_path.parent == wf_dir / "agents" else "shared"
        return {
            "name": name,
            "md_content": md_path.read_text(),
            "workflow": workflow,
            "source": source,
        }
    # Legacy path
    agents_dir_path = _validate_agents_dir(agents_dir)
    md_path = agents_dir_path / f"{name}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return {"name": name, "md_content": md_path.read_text(), "agents_dir": agents_dir}


@router.put("/agents/{name}/md")
async def update_agent_md(name: str, request: Request) -> dict:
    """Update an agent's Markdown file.

    Body fields:
      - ``md_content`` (str, required)
      - ``workflow`` (str, optional, new) + ``target`` ("private"|"shared", default
        "private"): write to ``workflows/<workflow>/agents/<name>.md`` or
        ``workflows/_shared/agents/<name>.md``.
      - ``agents_dir`` (str, legacy): write to ``<agents_dir>/<name>.md`` if the
        file already exists there.
    """
    body = await request.json()
    md_content = body.get("md_content", "")
    workflow = body.get("workflow")
    target = body.get("target", "private")

    if workflow is not None:
        if target not in ("private", "shared"):
            raise HTTPException(status_code=400, detail="target must be 'private' or 'shared'")
        if target == "private":
            wf_dir = _validate_workflow_dir(workflow)
            md_path = wf_dir / "agents" / f"{name}.md"
        else:
            md_path = _SHARED_AGENTS_DIR / f"{name}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        # Legacy path — require existing file at agents_dir/<name>.md
        agents_dir = body.get("agents_dir", "agents")
        agents_dir_path = _validate_agents_dir(agents_dir)
        md_path = agents_dir_path / f"{name}.md"
        if not md_path.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Validate before writing — write to temp file, parse, then rename
    tmp = md_path.with_suffix(".tmp")
    try:
        tmp.write_text(md_content)
        parsed = parse_agent_md(tmp)
        tmp.replace(md_path)
        return {
            "status": "ok",
            "name": parsed.name,
            "description": parsed.description,
            "path": str(md_path),
        }
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid agent MD: {e}")


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


@router.get("/workflows/definitions")
async def list_workflow_definitions() -> list[dict]:
    """List all saved workflow definitions (from workflows/*.json)."""
    return Workflow.list_saved()


@router.get("/runs", response_model=list[RunDetail])
async def list_runs(workflow_name: str | None = None) -> list[RunDetail]:
    """List persisted runs, merged with currently-running in-memory workflows.

    Live runs are returned with status="running" so the sidebar can show them
    alongside finished ones and offer a cancel button. They are merged by
    run_id — if a workflow finishes between sidebar refreshes, the persisted
    record takes precedence.
    """
    from harness.run_store import RunStore
    persisted = RunStore().list_runs(workflow_name=workflow_name)
    persisted_ids = {r.get("run_id") for r in persisted}

    # Add running in-memory workflows that aren't yet persisted
    live_records = []
    for wid, data in _workflows.items():
        if data["status"] != "running" or wid in persisted_ids:
            continue
        workflow = data["workflow"]
        if workflow_name and workflow.name != workflow_name:
            continue
        live_records.append({
            "run_id": wid,
            "workflow_name": workflow.name,
            "agents_snapshot": data.get("agents_snapshot", []),
            "status": "running",
            "inputs": data.get("inputs", {}),
            "result": None,
            "conversation": [],
            "created_at": data.get("created_at", ""),
            "dag": _dag_cache.get(wid),
        })

    # Live runs first (most recent), then persisted (sorted by created_at desc by RunStore)
    return live_records + persisted


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str) -> RunDetail:
    """Get a run by id — persisted disk record or live in-memory workflow."""
    from harness.run_store import RunStore
    run = RunStore().get_run(run_id)
    if run:
        return run

    # Fall back to in-memory live workflow
    data = _workflows.get(run_id)
    if data is not None:
        workflow = data["workflow"]
        return {
            "run_id": run_id,
            "workflow_name": workflow.name,
            "agents_snapshot": data.get("agents_snapshot", []),
            "status": data["status"],
            "inputs": data.get("inputs", {}),
            "result": data.get("result"),
            "conversation": [],
            "created_at": data.get("created_at", ""),
            "dag": _dag_cache.get(run_id),
        }

    raise HTTPException(status_code=404, detail="Run not found")


@router.patch("/runs/{run_id}/conversation")
async def update_run_conversation(run_id: str, request: Request) -> dict:
    """Update conversation messages for a persisted run."""
    body = await request.json()
    conversation = body.get("conversation", [])
    from harness.run_store import RunStore
    store = RunStore()
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run["conversation"] = conversation
    path = store._safe_path(run_id)
    if not path:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    import json
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False))
    return {"status": "ok"}


@router.patch("/runs/{run_id}/charts")
async def update_run_charts(run_id: str, request: Request) -> dict:
    """Update chart_groups snapshot for a persisted run (so Results tab replays)."""
    body = await request.json()
    chart_groups = body.get("chart_groups")
    from harness.run_store import RunStore
    store = RunStore()
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run["chart_groups"] = chart_groups
    path = store._safe_path(run_id)
    if not path:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    import json
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False))
    return {"status": "ok"}


@router.post("/workflows", response_model=CreateWorkflowResponse)
async def create_workflow(
    request: CreateWorkflowRequest,
    event_bus = Depends(get_event_bus),
) -> CreateWorkflowResponse:
    """Create and start a workflow."""
    # Block concurrent workflows — only one at a time
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count > 0:
        raise HTTPException(status_code=409, detail="A workflow is already running. Wait for it to complete or cancel it first.")

    # Clear EventBus replay buffer so the new WS subscriber doesn't receive
    # stale events from prior runs (e.g. ghost charts, replayed workflow.started
    # that would overwrite _activeWorkflowId on the client).
    event_bus.clear_buffer()

    workflow_id = str(uuid.uuid4())

    # Convert AgentDef to Agent (including new eval field)
    agents = [
        Agent(
            name=a.name,
            after=a.after,
            on_pass=a.on_pass,
            on_fail=a.on_fail,
            eval=a.eval,
        )
        for a in request.agents
    ]

    # Resolve workflow_dir: prefer explicit `workflow` field; else derive from name.
    if request.workflow:
        wf_dir = _validate_workflow_dir(request.workflow)
        workflow = Workflow(
            name=request.name,
            agents=agents,
            workflow_dir=wf_dir,
            tool_registry=ToolRegistry(),
            event_bus=event_bus,
        )
    else:
        # Legacy back-compat: caller passed agents_dir; Workflow.__init__ will
        # derive workflow_dir from it.
        workflow = Workflow(
            name=request.name,
            agents=agents,
            agents_dir=request.agents_dir,
            tool_registry=ToolRegistry(),
            event_bus=event_bus,
        )

    # Store workflow
    from datetime import datetime, timezone
    from server.runner import _build_agents_snapshot
    _workflows[workflow_id] = {
        "workflow": workflow,
        "status": "running",
        "result": None,
        "inputs": request.inputs,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Take agents_snapshot at workflow START so that mid-run .md edits don't
        # pollute history. The persisted record will use this exact snapshot.
        "agents_snapshot": _build_agents_snapshot(workflow),
    }

    # Build DAG for React Flow
    node_order = build_dag(agents)
    edges: list[list[str]] = []
    conditional_edges: list[dict] = []
    for a in agents:
        for dep in a.after:
            edges.append([dep, a.name])
        if a.on_pass is not None or a.on_fail is not None:
            if a.on_pass is not None:
                conditional_edges.append({"from": a.name, "to": a.on_pass, "label": "pass"})
            if a.on_fail is not None:
                conditional_edges.append({"from": a.name, "to": a.on_fail, "label": "fail"})
    _dag_cache[workflow_id] = {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges}

    # Emit workflow.started event (actual execution managed by WorkflowRunner)
    event_bus.emit("workflow.started", {
        "workflow_id": workflow_id,
        "name": workflow.name,
        "inputs": request.inputs,
        "dag": {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
        "workflow": request.workflow or request.name,
    })

    # Submit to runner
    from server.runner import get_runner
    runner = get_runner()
    await runner.submit(workflow_id, workflow, request.inputs, event_bus)

    return CreateWorkflowResponse(
        workflow_id=workflow_id,
        status="running",
        dag={"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
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