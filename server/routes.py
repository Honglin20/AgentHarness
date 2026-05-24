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
    CheckpointInfo,
    CreateWorkflowRequest,
    CreateWorkflowResponse,
    HealthResponse,
    ResumeRequest,
    RunDetail,
    ToolInfo,
    WorkflowStatusResponse,
)
from server.repository import get_repository

router = APIRouter()

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
    workflow: str,
) -> list[AgentInfo]:
    """List all available agents for a workflow.

    Resolution order:
      1. ``workflows/<workflow>/agents/*.md`` (private)
      2. ``workflows/_shared/agents/*.md`` (shared fallback)
    """
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


@router.get("/agents/{name}")
async def get_agent(
    name: str,
    workflow: str,
) -> AgentInfo:
    """Get a specific agent's definition."""
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


@router.get("/agents/{name}/md")
async def get_agent_md(
    name: str,
    workflow: str,
) -> dict:
    """Get the raw Markdown content of an agent definition.

    Resolution: ``resolve_agent_md(name, workflows/<workflow>)``
    which falls back to ``workflows/_shared/agents/`` if not found locally.
    """
    wf_dir = _validate_workflow_dir(workflow)
    try:
        md_path = resolve_agent_md(name, wf_dir)
    except AgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    source = "private" if md_path.parent == wf_dir / "agents" else "shared"
    return {
        "name": name,
        "md_content": md_path.read_text(),
        "workflow": workflow,
        "source": source,
    }


@router.put("/agents/{name}/md")
async def update_agent_md(name: str, request: Request) -> dict:
    """Update an agent's Markdown file.

    Body fields:
      - ``md_content`` (str, required)
      - ``workflow`` (str, required) + ``target`` ("private"|"shared", default
        "private"): write to ``workflows/<workflow>/agents/<name>.md`` or
        ``workflows/_shared/agents/<name>.md``.
    """
    body = await request.json()
    md_content = body.get("md_content", "")
    workflow = body.get("workflow")
    target = body.get("target", "private")

    if not workflow:
        raise HTTPException(status_code=400, detail="workflow is required")

    if target not in ("private", "shared"):
        raise HTTPException(status_code=400, detail="target must be 'private' or 'shared'")
    if target == "private":
        wf_dir = _validate_workflow_dir(workflow)
        md_path = wf_dir / "agents" / f"{name}.md"
    else:
        md_path = _SHARED_AGENTS_DIR / f"{name}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

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


@router.delete("/workflows/definitions/{name}")
async def delete_workflow_definition(name: str) -> dict:
    """Delete a saved workflow definition directory."""
    import shutil
    wf_dir = _validate_workflow_dir(name)
    if not wf_dir.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")
    shutil.rmtree(wf_dir)
    return {"status": "ok", "deleted": name}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str) -> dict:
    """Delete a persisted run record."""
    from harness.run_store import RunStore
    store = RunStore()
    path = store._safe_path(run_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    path.unlink()
    return {"status": "ok", "deleted": run_id}


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
    repo = get_repository()
    for wid, data in repo.all_running():
        if wid in persisted_ids:
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
            "dag": repo.get_dag(wid),
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
    repo = get_repository()
    data = repo.get(run_id)
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
            "dag": repo.get_dag(run_id),
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

    # Resolve workflow_dir from explicit `workflow` field.
    if not request.workflow:
        raise HTTPException(status_code=400, detail="workflow is required")
    wf_dir = _validate_workflow_dir(request.workflow)

    # Inject checkpointer for SQLite-backed checkpoints
    from harness.checkpoint import get_checkpoint_manager
    checkpoint_mgr = get_checkpoint_manager()
    checkpointer = await checkpoint_mgr.get_checkpointer()

    workflow = Workflow(
        name=request.name,
        agents=agents,
        workflow_dir=wf_dir,
        tool_registry=ToolRegistry(),
        event_bus=event_bus,
        checkpointer=checkpointer,
    )

    # Store workflow
    from datetime import datetime, timezone
    from server.runner import _build_agents_snapshot
    repo = get_repository()
    repo.put(workflow_id, {
        "workflow": workflow,
        "status": "running",
        "result": None,
        "inputs": request.inputs,
        "thread_id": workflow_id,  # for checkpoint resume
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Take agents_snapshot at workflow START so that mid-run .md edits don't
        # pollute history. The persisted record will use this exact snapshot.
        "agents_snapshot": _build_agents_snapshot(workflow),
    })

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
    repo.put_dag(workflow_id, {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges})

    # Emit workflow.started event (actual execution managed by WorkflowRunner)
    event_bus.emit("workflow.started", {
        "workflow_id": workflow_id,
        "name": workflow.name,
        "inputs": request.inputs,
        "dag": {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
        "workflow": request.workflow or request.name,
    })

    # Submit to runner (pass thread_id config for checkpointer)
    from server.runner import get_runner
    runner = get_runner()
    run_config = {"configurable": {"thread_id": workflow_id}}
    await runner.submit(workflow_id, workflow, request.inputs, event_bus, config=run_config)

    return CreateWorkflowResponse(
        workflow_id=workflow_id,
        status="running",
        dag={"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow(workflow_id: str) -> WorkflowStatusResponse:
    """Get workflow status and result."""
    if not get_repository().contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = get_repository().get(workflow_id)
    return WorkflowStatusResponse(
        workflow_id=workflow_id,
        name=data["workflow"].name,
        status=data["status"],
        result=data["result"],
    )


@router.post("/workflows/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: str,
    event_bus=Depends(get_event_bus),
) -> dict:
    """Pause a running workflow. Status becomes 'paused' and can be resumed."""
    if not get_repository().contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    from server.runner import get_runner
    runner = get_runner()

    paused = await runner.cancel(workflow_id)

    if paused:
        event_bus.emit("workflow.cancelled", {"workflow_id": workflow_id})

    return {"status": "paused" if paused else "running"}


@router.get("/workflows/{workflow_id}/dag")
async def get_workflow_dag(workflow_id: str) -> dict:
    """Get DAG structure for React Flow."""
    dag = get_repository().get_dag(workflow_id)
    if dag is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return dag


@router.get("/workflows/{workflow_id}/trace")
async def get_workflow_trace(workflow_id: str) -> dict:
    """Get execution trace."""
    repo = get_repository()
    if not repo.contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = repo.get(workflow_id)
    result = data["result"]

    if result is None:
        return {"workflow_id": workflow_id, "trace": []}

    return {
        "workflow_id": workflow_id,
        "trace": result.get("trace", []),
    }


@router.get("/runs/{run_id}/checkpoints", response_model=list[CheckpointInfo])
async def list_checkpoints(run_id: str) -> list[CheckpointInfo]:
    """List all checkpoints for a workflow run."""
    repo = get_repository()
    if not repo.contains(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    data = repo.get(run_id)
    workflow = data["workflow"]

    # Need compiled graph to query state history
    if workflow._compiled is None:
        return []

    from harness.checkpoint import get_checkpoint_manager
    mgr = get_checkpoint_manager()
    checkpoints = await mgr.list_checkpoints(workflow._compiled, thread_id=run_id)
    return [
        CheckpointInfo(
            checkpoint_id=cp["checkpoint_id"],
            thread_id=cp["thread_id"],
            next_nodes=cp["next_nodes"],
            values=cp["values"],
        )
        for cp in checkpoints
    ]


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    request: ResumeRequest,
    event_bus=Depends(get_event_bus),
) -> dict:
    """Resume a workflow from a checkpoint.

    If checkpoint_id is not provided, resumes from the latest non-final
    checkpoint (the last state that still has pending nodes).
    """
    if not get_repository().contains(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    from harness.checkpoint import get_checkpoint_manager
    mgr = get_checkpoint_manager()

    # Get workflow and compiled graph
    data = get_repository().get(run_id)
    workflow = data["workflow"]
    if workflow._compiled is None:
        raise HTTPException(status_code=400, detail="Workflow has no compiled graph")

    # Get checkpoint config
    if request.checkpoint_id:
        config = await mgr.get_checkpoint_config(workflow._compiled, run_id, request.checkpoint_id)
        if config is None:
            raise HTTPException(status_code=404, detail="Checkpoint not found")
    else:
        config = await mgr.get_latest_checkpoint_config(workflow._compiled, run_id)
        if config is None:
            raise HTTPException(status_code=400, detail="No resumable checkpoint found")

    # Block if already running
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count > 0:
        raise HTTPException(status_code=409, detail="A workflow is already running")

    event_bus.clear_buffer()

    # Emit resumed event
    event_bus.emit("workflow.started", {
        "workflow_id": run_id,
        "name": workflow.name,
        "inputs": data.get("inputs", {}),
        "dag": get_repository().get_dag(run_id),
        "resumed_from": config["configurable"].get("checkpoint_id"),
    })

    # Submit resume to runner
    await runner.submit(
        run_id, workflow, data.get("inputs", {}), event_bus,
        config=config, resume=True,
    )

    return {
        "workflow_id": run_id,
        "status": "running",
        "resumed_from": config["configurable"].get("checkpoint_id"),
    }


@router.post("/runs/{run_id}/rerun", response_model=CreateWorkflowResponse)
async def rerun(
    run_id: str,
    event_bus=Depends(get_event_bus),
) -> CreateWorkflowResponse:
    """Re-run a previous run with the same workflow config and inputs."""
    from harness.run_store import RunStore
    run = RunStore().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Block concurrent workflows
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count > 0:
        raise HTTPException(status_code=409, detail="A workflow is already running")

    event_bus.clear_buffer()

    workflow_name = run["workflow_name"]
    inputs = run.get("inputs", {})
    agents_snapshot = run.get("agents_snapshot", [])
    dag = run.get("dag")

    # Validate workflow dir
    wf_dir = _validate_workflow_dir(workflow_name)

    # Reconstruct agents from snapshot
    agents = [
        Agent(name=a["name"], after=a.get("after", []))
        for a in agents_snapshot
    ]

    new_id = str(uuid.uuid4())

    # Inject checkpointer
    from harness.checkpoint import get_checkpoint_manager
    checkpoint_mgr = get_checkpoint_manager()
    checkpointer = await checkpoint_mgr.get_checkpointer()

    workflow = Workflow(
        name=workflow_name,
        agents=agents,
        workflow_dir=wf_dir,
        tool_registry=ToolRegistry(),
        event_bus=event_bus,
        checkpointer=checkpointer,
    )

    from datetime import datetime, timezone
    from server.runner import _build_agents_snapshot
    repo = get_repository()
    repo.put(new_id, {
        "workflow": workflow,
        "status": "running",
        "result": None,
        "inputs": inputs,
        "thread_id": new_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agents_snapshot": _build_agents_snapshot(workflow),
    })

    # Build DAG from snapshot or recompute
    node_order = dag.get("nodes", [a.name for a in agents]) if dag else [a.name for a in agents]
    edges = dag.get("edges", []) if dag else []
    conditional_edges = dag.get("conditional_edges", []) if dag else []
    dag_struct = {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges}
    repo.put_dag(new_id, dag_struct)

    event_bus.emit("workflow.started", {
        "workflow_id": new_id,
        "name": workflow_name,
        "inputs": inputs,
        "dag": dag_struct,
        "workflow": workflow_name,
    })

    run_config = {"configurable": {"thread_id": new_id}}
    await runner.submit(new_id, workflow, inputs, event_bus, config=run_config)

    return CreateWorkflowResponse(
        workflow_id=new_id,
        status="running",
        dag=dag_struct,
    )