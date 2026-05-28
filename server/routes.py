"""REST API routes."""

import json
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
    CreateBatchRequest,
    CreateBatchResponse,
    CreateWorkflowRequest,
    CreateWorkflowResponse,
    HealthResponse,
    ResumeRequest,
    RunDetail,
    BatchRunSummary,
    BenchmarkDef,
    BenchmarkRunSummary,
    BenchmarkTaskResult,
    RunBenchmarkRequest,
    ToolInfo,
    WorkflowStatusResponse,
)
from server.repository import get_repository

from harness.user_manager import get_current_user, get_user_manager

router = APIRouter()


@router.get("/me")
async def get_me(request: Request) -> dict:
    """Get current user info based on X-User-Id or X-API-Key header"""
    user = get_current_user(request)
    return {
        "user_id": user.user_id,
        "name": user.name,
        "role": user.role,
    }


@router.get("/users")
async def list_users() -> list[dict]:
    """List all users."""
    mgr = get_user_manager()
    return [u.model_dump() for u in mgr.list_users()]


@router.post("/users")
async def create_user(request: Request) -> dict:
    """Create a new user (admin only)."""
    user = get_current_user(request)
    mgr = get_user_manager()
    if not mgr.is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")

    body = await request.json()
    user_id = body.get("user_id", "").strip()
    name = body.get("name", "").strip()
    role = body.get("role", "developer")

    if not user_id or not name:
        raise HTTPException(status_code=400, detail="user_id and name are required")
    if role not in ("developer", "admin"):
        raise HTTPException(status_code=400, detail="role must be 'developer' or 'admin'")

    try:
        new_user = mgr.create_user(user_id, name, role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return new_user.model_dump()


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request) -> dict:
    """Delete a user (admin only)."""
    user = get_current_user(request)
    mgr = get_user_manager()
    if not mgr.is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        mgr.delete_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "ok", "deleted": user_id}


def _check_workflow_owner(workflow_id: str, request: Request) -> None:
    """Check that the current user owns the in-memory workflow (or is admin)."""
    repo = get_repository()
    if not repo.contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    user = get_current_user(request)
    if not get_user_manager().is_admin(user):
        owner = repo.get(workflow_id).get("user_id", "default")
        if owner != user.user_id:
            raise HTTPException(status_code=403, detail="Not your workflow")


def _validate_workflow_dir(workflow: str, user_id: str | None = None) -> Path:
    """Validate a workflow folder name and return its absolute path.

    Search order:
      0. Registry (builtin + project + extra registrations)
      1. workflows/_shared/workflows/{workflow}/
      2. workflows/users/{user_id}/workflows/{workflow}/
      3. workflows/{workflow}/ (legacy)

    Args:
        workflow: Workflow name
        user_id: Optional user ID for private workflows

    Rejects path traversal. The directory does not need to exist (caller decides).
    """
    if not workflow or "/" in workflow or "\\" in workflow or workflow.startswith("."):
        raise HTTPException(status_code=400, detail="invalid workflow name")

    # Try registry first (builtin + project resources)
    from harness.registry import get_registry
    try:
        return get_registry().resolve_workflow(workflow).resource_dir
    except FileNotFoundError:
        pass

    # Try shared workflows first
    shared_path = (_WORKFLOWS_DIR / "_shared" / "workflows" / workflow).resolve()
    if str(shared_path).startswith(str(_WORKFLOWS_DIR.resolve())) and (shared_path / "workflow.json").exists():
        return shared_path

    # Try user's private workflows
    if user_id and user_id != "default":
        private_path = (_WORKFLOWS_DIR / "users" / user_id / "workflows" / workflow).resolve()
        if str(private_path).startswith(str(_WORKFLOWS_DIR.resolve())) and (private_path / "workflow.json").exists():
            return private_path

    # Fallback: workflows/{workflow}/ (legacy or already-resolved path)
    resolved = (_WORKFLOWS_DIR / workflow).resolve()
    if not str(resolved).startswith(str(_WORKFLOWS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="workflow escapes workflows root")
    return resolved


def get_event_bus():
    """Legacy shim — returns global Bus.

    Prefer creating a new Bus per workflow via _new_bus() below.
    """
    from server.event_bus import get_event_bus
    return get_event_bus()


def _new_bus():
    """Create a fresh Bus with default hooks registered."""
    from harness.extensions.bus import Bus
    from harness.extensions.plugins import register_default_hooks
    bus = Bus()
    register_default_hooks(bus)
    return bus


def _get_bus_for_workflow(workflow_id: str):
    """Retrieve the Bus bound to a specific workflow, or create a fallback with hooks."""
    repo = get_repository()
    data = repo.get(workflow_id)
    if data and data.get("event_bus"):
        return data["event_bus"]
    return _new_bus()


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
    request: Request,
) -> list[AgentInfo]:
    """List all available agents for a workflow.

    Resolution order:
      1. ``workflows/<workflow>/agents/*.md`` (private)
      2. ``workflows/_shared/agents/*.md`` (shared fallback)
    """
    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None
    wf_dir = _validate_workflow_dir(workflow, user_id)
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
    request: Request,
) -> AgentInfo:
    """Get a specific agent's definition."""
    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None
    wf_dir = _validate_workflow_dir(workflow, user_id)
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
    request: Request,
) -> dict:
    """Get the raw Markdown content of an agent definition.

    Resolution: ``resolve_agent_md(name, workflows/<workflow>)``
    which falls back to ``workflows/_shared/agents/`` if not found locally.
    """
    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None
    wf_dir = _validate_workflow_dir(workflow, user_id)
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
        user = get_current_user(request)
        user_id = user.user_id if user.user_id != "default" else None
        wf_dir = _validate_workflow_dir(workflow, user_id)
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
async def chart_render(request: Request) -> dict:
    """Receive chart payload from render_chart() HTTP fallback and emit via EventBus."""
    body = await request.json()
    node_id = body.get("node_id", "")
    chart = body.get("chart", {})

    repo = get_repository()
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
                event_bus = data.get("event_bus")
                if event_bus:
                    event_bus.emit("chart.render", event_payload)
                    return {"status": "ok"}

    # If node_id is empty or no specific match, try the active (last-started) running workflow
    running = list(repo.all_running())
    if running:
        _wid, data = running[-1]
        event_bus = data.get("event_bus")
        if event_bus:
            event_bus.emit("chart.render", event_payload)
            return {"status": "ok"}

    # Fallback: emit on global bus for backwards compat
    get_event_bus().emit("chart.render", event_payload)

    return {"status": "ok"}


@router.get("/workflows/definitions")
async def list_workflow_definitions(request: Request) -> list[dict]:
    """List saved workflow definitions: shared + current user's private."""
    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None
    return Workflow.list_saved(user_id=user_id)


@router.delete("/workflows/definitions/{name}")
async def delete_workflow_definition(name: str, request: Request) -> dict:
    """Delete a saved workflow definition directory.

    Only admin can delete shared workflows.
    Users can only delete their own private workflows.
    """
    import shutil
    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()

    # Find the workflow and determine its scope
    user_id = user.user_id if user.user_id != "default" else None
    workflows = Workflow.list_saved(user_id=user_id)
    target = next((w for w in workflows if w["name"] == name), None)

    if not target:
        raise HTTPException(status_code=404, detail="Workflow not found")

    scope = target.get("scope", "legacy")

    # Check permissions
    if not user_mgr.can_delete_workflow(user, scope, user.user_id):
        if scope == "shared":
            raise HTTPException(status_code=403, detail="Cannot delete shared workflow (admin only)")
        else:
            raise HTTPException(status_code=403, detail="Cannot delete workflow (not yours)")

    wf_dir = Path(target["workflow_dir"])
    if not wf_dir.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")
    shutil.rmtree(wf_dir)
    return {"status": "ok", "deleted": name}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, request: Request) -> dict:
    """Delete a persisted run record.

    Only the run owner or admin can delete.
    """
    from harness.run_store import RunStore
    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    store = RunStore()
    run = store.get_run(run_id)

    # Check if run belongs to user (or admin)
    if run and not is_admin and run.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    # Also check in-memory runs
    repo = get_repository()
    data = repo.get(run_id)
    if data and not is_admin and data.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    path = store._safe_path(run_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    path.unlink()
    repo.remove(run_id)
    return {"status": "ok", "deleted": run_id}


@router.get("/runs", response_model=list[RunDetail])
async def list_runs(request: Request, workflow_name: str | None = None) -> list[RunDetail]:
    """List persisted runs, merged with currently-running in-memory workflows.

    Only returns runs for the current user (admin sees all).

    Live runs are returned with status="running" so the sidebar can show them
    alongside finished ones and offer a cancel button. They are merged by
    run_id — if a workflow finishes between sidebar refreshes, the persisted
    record takes precedence.

    Batch runs (runs that are part of a benchmark) are excluded by default.
    """
    from harness.run_store import RunStore
    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    persisted = RunStore().list_runs(
        workflow_name=workflow_name,
        include_batch=True,
        user_id=None if is_admin else user.user_id,
    )
    persisted_ids = {r.get("run_id") for r in persisted}

    # Add running in-memory workflows that aren't yet persisted
    live_records = []
    repo = get_repository()
    for wid, data in repo.all_running():
        if wid in persisted_ids:
            continue
        # Filter by user (unless admin)
        if not is_admin and data.get("user_id", "default") != user.user_id:
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
async def get_run(run_id: str, request: Request) -> RunDetail:
    """Get a run by id — persisted disk record or live in-memory workflow."""
    from harness.run_store import RunStore
    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    run = RunStore().get_run(run_id)
    if run:
        if not is_admin and run.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        # Ensure all fields from RunDetail are present
        return {
            "run_id": run.get("run_id"),
            "workflow_name": run.get("workflow_name"),
            "agents_snapshot": run.get("agents_snapshot", []),
            "status": run.get("status"),
            "inputs": run.get("inputs", {}),
            "result": run.get("result"),
            "conversation": run.get("conversation", []),
            "created_at": run.get("created_at", ""),
            "dag": run.get("dag"),
            "chart_groups": run.get("chart_groups"),
            "agent_io": run.get("agent_io"),
            "batch_id": run.get("batch_id"),
            "user_id": run.get("user_id"),
        }

    # Fall back to in-memory live workflow
    repo = get_repository()
    data = repo.get(run_id)
    if data is not None:
        if not is_admin and data.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        workflow = data["workflow"]
        return {
            "run_id": run_id,
            "workflow_name": workflow.name,
            "agents_snapshot": data.get("agents_snapshot", []),
            "status": data["status"],
            "inputs": data.get("inputs", {}),
            "result": data.get("result"),
            "conversation": data.get("conversation", []),
            "created_at": data.get("created_at", ""),
            "dag": repo.get_dag(run_id),
            "chart_groups": None,
            "agent_io": None,
            "batch_id": data.get("batch_id"),
            "user_id": data.get("user_id"),
        }

    raise HTTPException(status_code=404, detail="Run not found")


@router.patch("/runs/{run_id}/conversation")
async def update_run_conversation(run_id: str, request: Request) -> dict:
    """Update conversation messages for a run — persisted or in-memory."""
    body = await request.json()
    conversation = body.get("conversation", [])

    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    # Try persisted run first
    from harness.run_store import RunStore
    store = RunStore()
    run = store.get_run(run_id)
    if run:
        if not is_admin and run.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        run["conversation"] = conversation
        path = store._safe_path(run_id)
        if not path:
            raise HTTPException(status_code=400, detail="Invalid run_id")
        import json
        path.write_text(json.dumps(run, indent=2, ensure_ascii=False))
        return {"status": "ok"}

    # For in-memory running workflows, store conversation in repository
    repo = get_repository()
    data = repo.get(run_id)
    if data is not None:
        if not is_admin and data.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        data["conversation"] = conversation
        return {"status": "ok"}

    raise HTTPException(status_code=404, detail="Run not found")


@router.patch("/runs/{run_id}/charts")
async def update_run_charts(run_id: str, request: Request) -> dict:
    """Update chart_groups snapshot for a persisted run (so Results tab replays)."""
    body = await request.json()
    chart_groups = body.get("chart_groups")

    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    from harness.run_store import RunStore
    store = RunStore()
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not is_admin and run.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")
    run["chart_groups"] = chart_groups
    path = store._safe_path(run_id)
    if not path:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    import json
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False))
    return {"status": "ok"}


async def _create_and_start_workflow(
    name: str,
    agents_defs: list[AgentDef],
    workflow_name: str,
    inputs: dict,
    batch_id: str | None = None,
    work_dir: str | None = None,
    user_id: str | None = None,
) -> CreateWorkflowResponse:
    """Core logic: create a Workflow, compile it, and submit to runner.

    Shared by create_workflow (single run) and create_batch (batch run).
    Creates an isolated Bus per workflow for concurrency safety.

    Args:
        work_dir: Working directory to execute in
        user_id: User ID who initiated this run
    """
    workflow_id = str(uuid.uuid4())

    # Each workflow gets its own Bus — fully isolated events + extensions
    event_bus = _new_bus()

    agents = [
        Agent(
            name=a.name,
            after=a.after,
            on_pass=a.on_pass,
            on_fail=a.on_fail,
            eval=a.eval,
        )
        for a in agents_defs
    ]

    wf_dir = _validate_workflow_dir(workflow_name, user_id)

    from harness.checkpoint import get_checkpoint_manager
    checkpoint_mgr = get_checkpoint_manager()
    checkpointer = await checkpoint_mgr.get_checkpointer()

    workflow = Workflow(
        name=name,
        agents=agents,
        workflow_dir=wf_dir,
        tool_registry=ToolRegistry(),
        event_bus=event_bus,
        checkpointer=checkpointer,
    )

    from harness.extensions.eval import EvalJudge

    has_eval = any(a.eval for a in agents)
    if has_eval:
        # Validate LLM config before mutation — fail fast if no model available
        import os
        judge_model = os.environ.get("HARNESS_MODEL", "")
        if not judge_model:
            raise HTTPException(
                status_code=400,
                detail="LLM model not configured. Set HARNESS_MODEL in Settings to use the eval feature.",
            )
        workflow.use(EvalJudge(max_retries=2))
        # Apply mutation NOW so the DAG includes _judge_X nodes
        for mutator in event_bus.get_mutators():
            workflow = mutator.mutate(workflow)

    from datetime import datetime, timezone
    from server.runner import _build_agents_snapshot
    repo = get_repository()
    repo.put(workflow_id, {
        "workflow": workflow,
        "status": "running",
        "result": None,
        "inputs": inputs,
        "thread_id": workflow_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agents_snapshot": _build_agents_snapshot(workflow),
        "batch_id": batch_id,
        "event_bus": event_bus,
        "user_id": user_id,
        "work_dir": work_dir,
    })

    # Build DAG from mutated agents (includes _judge_X nodes when eval=True)
    mutated_agents = workflow.agents
    node_order = build_dag(mutated_agents)
    edges: list[list[str]] = []
    conditional_edges: list[dict] = []
    for a in mutated_agents:
        for dep in a.after or []:
            edges.append([dep, a.name])
        if a.on_pass is not None or a.on_fail is not None:
            if a.on_pass is not None:
                conditional_edges.append({"from": a.name, "to": a.on_pass, "label": "pass"})
            if a.on_fail is not None:
                conditional_edges.append({"from": a.name, "to": a.on_fail, "label": "fail"})
    dag = {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges}
    repo.put_dag(workflow_id, dag)

    event_bus.emit("workflow.started", {
        "workflow_id": workflow_id,
        "user_id": user_id,
        "name": workflow.name,
        "inputs": inputs,
        "dag": dag,
        "workflow": workflow_name,
        "batch_id": batch_id,
    })

    from server.runner import get_runner
    runner = get_runner()
    run_config = {"configurable": {"thread_id": workflow_id}}
    await runner.submit(
        workflow_id, workflow, inputs, event_bus,
        config=run_config, work_dir=work_dir, user_id=user_id
    )

    return CreateWorkflowResponse(
        workflow_id=workflow_id,
        status="running",
        dag=dag,
    )


@router.post("/workflows", response_model=CreateWorkflowResponse)
async def create_workflow(
    request: Request,
) -> CreateWorkflowResponse:
    """Create and start a single workflow."""
    from server.runner import get_runner

    user = get_current_user(request)

    body = await request.json()
    request_obj = CreateWorkflowRequest(**body)

    runner = get_runner()
    if runner.running_count >= runner.max_concurrent:
        raise HTTPException(status_code=409, detail=f"Max {runner.max_concurrent} concurrent workflows. Wait for one to finish.")

    if not request_obj.workflow:
        raise HTTPException(status_code=400, detail="workflow is required")

    return await _create_and_start_workflow(
        name=request_obj.name,
        agents_defs=request_obj.agents,
        workflow_name=request_obj.workflow,
        inputs=request_obj.inputs,
        work_dir=request_obj.work_dir,
        user_id=user.user_id,
    )


@router.post("/batch", response_model=CreateBatchResponse)
async def create_batch(
    request: Request,
) -> CreateBatchResponse:
    """Create and start a batch of workflow runs with different inputs.

    Each item in `items` becomes an independent workflow run.
    All runs share the same workflow definition (agents + prompts).
    Each run gets its own isolated Bus.
    """
    user = get_current_user(request)
    body = await request.json()
    request_obj = CreateBatchRequest(**body)

    from server.runner import get_runner
    runner = get_runner()

    if not request_obj.workflow:
        raise HTTPException(status_code=400, detail="workflow is required")
    if not request_obj.items:
        raise HTTPException(status_code=400, detail="items must not be empty")

    batch_id = str(uuid.uuid4())
    runs: list[BatchRunSummary] = []

    for item in request_obj.items:
        result = await _create_and_start_workflow(
            name=request_obj.name,
            agents_defs=request_obj.agents,
            workflow_name=request_obj.workflow,
            inputs=item.inputs,
            batch_id=batch_id,
            user_id=user.user_id,
        )
        runs.append(BatchRunSummary(
            workflow_id=result.workflow_id,
            label=item.label,
            status="running",
        ))

    # Store batch metadata
    repo = get_repository()
    batch_meta: dict = {
        "batch_id": batch_id,
        "name": request_obj.name,
        "workflow": request_obj.workflow,
        "runs": {r.workflow_id: {"label": r.label, "status": r.status} for r in runs if r.workflow_id},
    }
    if user.user_id != "default":
        batch_meta["user_id"] = user.user_id
    repo.put_batch(batch_id, batch_meta)

    return CreateBatchResponse(batch_id=batch_id, runs=runs)


@router.get("/batch/{batch_id}", response_model=CreateBatchResponse)
async def get_batch_status(batch_id: str, request: Request) -> CreateBatchResponse:
    """Get the status of all runs in a batch."""
    repo = get_repository()
    batch = repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    user = get_current_user(request)
    if not get_user_manager().is_admin(user):
        owner = batch.get("user_id", "default")
        if owner != user.user_id:
            raise HTTPException(status_code=403, detail="Not your batch")

    runs: list[BatchRunSummary] = []
    for wid, meta in batch.get("runs", {}).items():
        data = repo.get(wid)
        if data:
            status = data["status"]
            result = data.get("result")
            error = None
            score = None
            if status == "failed" and result:
                error = result.get("errors", {}).get("_workflow")
            if result:
                outputs = result.get("outputs", {})
                for key, val in outputs.items():
                    if isinstance(val, dict) and "score" in val:
                        score = val["score"]
                        break
            runs.append(BatchRunSummary(
                workflow_id=wid,
                label=meta.get("label", ""),
                status=status,
                score=score,
                error=error,
            ))
        else:
            runs.append(BatchRunSummary(
                workflow_id=wid,
                label=meta.get("label", ""),
                status=meta.get("status", "unknown"),
            ))

    return CreateBatchResponse(batch_id=batch_id, runs=runs)


# ---------------------------------------------------------------------------
# Benchmark endpoints
# ---------------------------------------------------------------------------

from harness.benchmark_store import BenchmarkStore as _BenchmarkStore


def _get_benchmark_store() -> _BenchmarkStore:
    return _BenchmarkStore()


@router.get("/benchmarks")
async def list_benchmarks() -> list[dict]:
    """List all saved benchmarks (shared across users)."""
    return _get_benchmark_store().list_benchmarks()


@router.post("/benchmarks")
async def create_benchmark(body: BenchmarkDef) -> dict:
    """Create a new benchmark."""
    store = _get_benchmark_store()
    tasks = [t.model_dump() for t in body.tasks]
    prep = body.prep.model_dump(exclude_none=True) if body.prep else None
    path = store.save_benchmark(body.name, tasks, description=body.description, prep=prep)
    return {"name": body.name, "path": str(path)}


@router.get("/benchmarks/{name}")
async def get_benchmark(name: str) -> dict:
    """Get benchmark definition."""
    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return bm


@router.put("/benchmarks/{name}")
async def update_benchmark(name: str, body: BenchmarkDef) -> dict:
    """Update benchmark tasks."""
    store = _get_benchmark_store()
    existing = store.load_benchmark(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    tasks = [t.model_dump() for t in body.tasks]
    prep = body.prep.model_dump(exclude_none=True) if body.prep else None
    store.save_benchmark(name, tasks, description=body.description, prep=prep)
    return {"name": name, "tasks": len(tasks)}


@router.delete("/benchmarks/{name}")
async def delete_benchmark(name: str) -> dict:
    """Delete a benchmark and all its results."""
    store = _get_benchmark_store()
    if not store.delete_benchmark(name):
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return {"deleted": name}


@router.post("/benchmarks/{name}/run", response_model=BenchmarkRunSummary)
async def run_benchmark(
    name: str,
    body: RunBenchmarkRequest,
    request: Request,
) -> BenchmarkRunSummary:
    """Run a benchmark with a specific workflow.

    Creates one workflow run per task, tracks progress, and persists results.
    """
    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None

    # Load workflow definition
    wf_dir = _validate_workflow_dir(body.workflow, user_id)
    wf_json = wf_dir / "workflow.json"
    if not wf_json.exists():
        raise HTTPException(status_code=404, detail=f"Workflow '{body.workflow}' not found")
    wf_data = json.loads(wf_json.read_text())
    agents_defs = [AgentDef(**a) for a in wf_data.get("agents", [])]

    # --- Prep phase: run once before all tasks if defined ---
    prep_config = bm.get("prep")
    if prep_config:
        from harness.prep_executor import run_prep, PrepError
        try:
            await run_prep(
                prep_config,
                benchmark_name=name,
                user_id=user_id,
            )
        except PrepError as e:
            raise HTTPException(status_code=422, detail=f"Prep phase failed: {e}")

    # Create batch runs directly (inline version of create_batch logic)
    batch_id = str(uuid.uuid4())
    runs: list[BatchRunSummary] = []

    for item in bm["tasks"]:
        result = await _create_and_start_workflow(
            name=name,
            agents_defs=agents_defs,
            workflow_name=body.workflow,
            inputs=item.get("inputs", {"task": item["label"]}),
            batch_id=batch_id,
            user_id=user_id,
        )
        runs.append(BatchRunSummary(
            workflow_id=result.workflow_id,
            label=item["label"],
            status="running",
        ))

    # Store batch metadata
    repo = get_repository()
    batch_meta: dict = {
        "batch_id": batch_id,
        "name": name,
        "workflow": body.workflow,
        "runs": {r.workflow_id: {"label": r.label, "status": r.status} for r in runs if r.workflow_id},
    }
    if user_id:
        batch_meta["user_id"] = user_id
    repo.put_batch(batch_id, batch_meta)

    # Build result record
    from datetime import datetime, timezone
    task_results = []
    for i, run in enumerate(runs):
        task_results.append({
            "task_id": bm["tasks"][i].get("id", f"task_{i + 1}"),
            "label": run.label,
            "status": run.status,
            "workflow_id": run.workflow_id,
        })

    result = {
        "run_id": batch_id,
        "benchmark_name": name,
        "workflow_name": body.workflow,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_results": task_results,
    }
    if user_id:
        result["user_id"] = user_id
    store.save_result(name, result)

    return BenchmarkRunSummary(
        run_id=batch_id,
        benchmark_name=name,
        workflow_name=body.workflow,
        status="running",
        created_at=result["created_at"],
        task_results=[
            BenchmarkTaskResult(
                task_id=tr["task_id"],
                label=tr["label"],
                status=tr["status"],
            )
            for tr in task_results
        ],
    )


@router.get("/benchmarks/{name}/results")
async def list_benchmark_results(name: str, request: Request) -> list[dict]:
    """List all run results for a benchmark, enriched with live scores."""
    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    user = get_current_user(request)
    user_mgr = get_user_manager()
    uid = None if user_mgr.is_admin(user) else user.user_id

    results = store.list_results(name, user_id=uid)

    repo = get_repository()
    for result in results:
        _enrich_benchmark_result(result, repo, store, name)

    return results


def _enrich_benchmark_result(result: dict, repo, store=None, benchmark_name: str = "") -> None:
    """Enrich a benchmark result with live scores, charts, and status from the repository.

    Persists enriched data back to disk so it survives server restarts.
    """
    task_results = result.get("task_results", [])
    changed = False
    scores = []

    for tr in task_results:
        wid = tr.get("workflow_id", "")
        if not wid:
            continue
        data = repo.get(wid)
        if not data:
            continue

        tr["status"] = data["status"]
        changed = True

        wf_result = data.get("result")
        if not wf_result:
            continue

        outputs = wf_result.get("outputs", {})

        # Extract scores: _judge_ prefix first, then fall back to any dict with a "score" key
        score = None
        for key, val in outputs.items():
            if not isinstance(val, dict):
                continue
            if key.startswith("_judge_"):
                judgment = val.get("_judgment", {})
                score = judgment.get("score")
            elif "score" in val:
                score = val.get("score")
            if score is not None:
                break

        if score is not None:
            tr["score"] = score
            scores.append(score)
            changed = True

        # Extract duration from trace
        trace = wf_result.get("trace", [])
        for entry in trace:
            if entry.get("agent_name") == tr.get("label") or (trace and not tr.get("duration_ms")):
                dur = entry.get("duration_ms")
                if dur:
                    tr["duration_ms"] = dur
                    changed = True
                break

    # Compute summary
    if scores:
        result["avg_score"] = sum(scores) / len(scores)

    # Check if all tasks completed
    all_done = all(
        tr.get("status") in ("completed", "failed")
        for tr in task_results
    )
    result["status"] = "completed" if all_done else "running"

    # Persist enriched data back to disk
    if changed and store and benchmark_name:
        store.save_result(benchmark_name, result)


@router.get("/benchmarks/{name}/results/{run_id}")
async def get_benchmark_result(name: str, run_id: str, request: Request) -> dict:
    """Get a specific benchmark run result with aggregated scores."""
    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    result = store.get_result(run_id, benchmark_name=name)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    repo = get_repository()
    _enrich_benchmark_result(result, repo, store, name)

    return result


@router.get("/workflows/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow(workflow_id: str, request: Request) -> WorkflowStatusResponse:
    """Get workflow status and result."""
    if not get_repository().contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = get_repository().get(workflow_id)
    user = get_current_user(request)
    if not get_user_manager().is_admin(user):
        owner = data.get("user_id", "default")
        if owner != user.user_id:
            raise HTTPException(status_code=403, detail="Not your workflow")

    return WorkflowStatusResponse(
        workflow_id=workflow_id,
        name=data["workflow"].name,
        status=data["status"],
        result=data["result"],
    )


@router.post("/workflows/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str, request: Request) -> dict:
    """Pause a running workflow. Status becomes 'paused' and can be resumed."""
    repo = get_repository()
    if not repo.contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = repo.get(workflow_id)
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    if not is_admin and data.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your workflow")

    from server.runner import get_runner
    runner = get_runner()

    paused = await runner.cancel(workflow_id)

    # Clear any pending stop-and-regenerate signals so they don't
    # trigger on resume
    from harness.engine.macro_graph import clear_stop_regen
    clear_stop_regen(workflow_id)

    if paused:
        event_bus = _get_bus_for_workflow(workflow_id)
        event_bus.emit("workflow.cancelled", {"workflow_id": workflow_id})

    return {"status": "paused" if paused else "running"}


@router.get("/workflows/{workflow_id}/dag")
async def get_workflow_dag(workflow_id: str, request: Request) -> dict:
    """Get DAG structure for React Flow."""
    dag = get_repository().get_dag(workflow_id)
    if dag is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    _check_workflow_owner(workflow_id, request)
    return dag


@router.get("/workflows/{workflow_id}/trace")
async def get_workflow_trace(workflow_id: str, request: Request) -> dict:
    """Get execution trace."""
    repo = get_repository()
    if not repo.contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    _check_workflow_owner(workflow_id, request)

    data = repo.get(workflow_id)
    result = data["result"]

    if result is None:
        return {"workflow_id": workflow_id, "trace": []}

    return {
        "workflow_id": workflow_id,
        "trace": result.get("trace", []),
    }


@router.get("/runs/{run_id}/checkpoints", response_model=list[CheckpointInfo])
async def list_checkpoints(run_id: str, request: Request) -> list[CheckpointInfo]:
    """List all checkpoints for a workflow run."""
    repo = get_repository()
    if not repo.contains(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    user = get_current_user(request)
    if not get_user_manager().is_admin(user):
        owner = repo.get(run_id).get("user_id", "default")
        if owner != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")

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
    body: ResumeRequest,
    req: Request,
) -> dict:
    """Resume a workflow from a checkpoint.

    If checkpoint_id is not provided, resumes from the latest non-final
    checkpoint (the last state that still has pending nodes).
    """
    repo = get_repository()
    if not repo.contains(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    data = repo.get(run_id)
    user = get_current_user(req)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    if not is_admin and data.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    from harness.checkpoint import get_checkpoint_manager
    mgr = get_checkpoint_manager()

    # Get workflow and compiled graph
    workflow = data["workflow"]
    if workflow._compiled is None:
        raise HTTPException(status_code=400, detail="Workflow has no compiled graph")

    run_user_id = data.get("user_id", user.user_id)

    # Get checkpoint config
    if body.checkpoint_id:
        config = await mgr.get_checkpoint_config(workflow._compiled, run_id, body.checkpoint_id)
        if config is None:
            raise HTTPException(status_code=404, detail="Checkpoint not found")
    else:
        config = await mgr.get_latest_checkpoint_config(workflow._compiled, run_id)
        if config is None:
            raise HTTPException(status_code=400, detail="No resumable checkpoint found")

    # Block if already at capacity
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count >= runner.max_concurrent:
        raise HTTPException(status_code=409, detail=f"Max {runner.max_concurrent} concurrent workflows. Wait for one to finish.")

    # Use the workflow's existing Bus (isolated per workflow)
    event_bus = data.get("event_bus") or _new_bus()

    # Emit resumed event
    with event_bus.with_user_context(run_user_id):
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
        config=config, resume=True, user_id=run_user_id,
    )

    return {
        "workflow_id": run_id,
        "status": "running",
        "resumed_from": config["configurable"].get("checkpoint_id"),
    }


@router.post("/runs/{run_id}/rerun", response_model=CreateWorkflowResponse)
async def rerun(
    run_id: str,
    request: Request,
) -> CreateWorkflowResponse:
    """Re-run a previous run with the same workflow config and inputs."""
    from harness.run_store import RunStore
    run = RunStore().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    if not is_admin and run.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    # Block concurrent workflows at capacity
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count >= runner.max_concurrent:
        raise HTTPException(status_code=409, detail=f"Max {runner.max_concurrent} concurrent workflows. Wait for one to finish.")

    workflow_name = run["workflow_name"]
    inputs = run.get("inputs", {})
    agents_snapshot = run.get("agents_snapshot", [])
    dag = run.get("dag")
    user_id = user.user_id if user.user_id != "default" else None

    # Validate workflow dir
    wf_dir = _validate_workflow_dir(workflow_name, user_id)

    # Reconstruct agents from snapshot
    agents = [
        Agent(name=a["name"], after=a.get("after", []))
        for a in agents_snapshot
    ]

    new_id = str(uuid.uuid4())

    # Create isolated Bus for this rerun
    event_bus = _new_bus()

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

    # Auto-register extensions based on agent flags
    from harness.extensions.eval import EvalJudge

    has_eval = any(getattr(a, "eval", False) for a in agents)
    if has_eval:
        workflow.use(EvalJudge(max_retries=2))

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
        "event_bus": event_bus,
        "user_id": user.user_id,
    })

    # Build DAG from snapshot or recompute
    node_order = dag.get("nodes", [a.name for a in agents]) if dag else [a.name for a in agents]
    edges = dag.get("edges", []) if dag else []
    conditional_edges = dag.get("conditional_edges", []) if dag else []
    dag_struct = {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges}
    repo.put_dag(new_id, dag_struct)

    with event_bus.with_user_context(user.user_id):
        event_bus.emit("workflow.started", {
            "workflow_id": new_id,
            "name": workflow_name,
            "inputs": inputs,
            "dag": dag_struct,
            "workflow": workflow_name,
        })

    run_config = {"configurable": {"thread_id": new_id}}
    await runner.submit(new_id, workflow, inputs, event_bus, config=run_config, user_id=user.user_id)

    return CreateWorkflowResponse(
        workflow_id=new_id,
        status="running",
        dag=dag_struct,
    )