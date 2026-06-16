"""Run persistence + lifecycle endpoints (list/get/delete/update/resume/rerun)."""
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from harness.api import Agent, Workflow
from harness.run_store_interface import RunStoreInterface
from harness.tools.registry import ToolRegistry
from harness.user_manager import get_current_user, get_user_manager
from server._helpers import (
    _check_not_modified,
    _create_and_start_workflow,
    _live_run_detail,
    _load_conversation_for_user,
    _new_bus,
    _persisted_run_detail,
    _reconstruct_run_to_repo,
    _validate_workflow_dir,
)
from server.dependencies import (
    get_repository_dep,
    get_runner_dep,
    get_run_store_dep,
)
from server.repository import WorkflowRepository
from server.runner import WorkflowRunner
from server.schemas import (
    BatchDeleteRunsRequest,
    CheckpointInfo,
    CreateWorkflowResponse,
    ResumeRequest,
    RunDetail,
    UpdateRunChartsRequest,
    UpdateRunConversationRequest,
    UpdateRunFollowupRequest,
)

router = APIRouter()

def _load_run_for_user(run_id: str, request: Request, store: RunStoreInterface):
    """Common loader: returns (store, run, user, is_admin). Raises 404/403.

    NOTE: helper takes the store as a parameter because it is called from
    FastAPI handlers. The handler receives the store via Depends() and
    passes it down. Helpers cannot use Depends() themselves.
    """
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not is_admin and run.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")
    return store, run, user, is_admin

@router.delete("/runs/{run_id}")
async def delete_run(
    run_id: str, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Delete a persisted run record. Only the run owner or admin can delete."""
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    run = store.get_run(run_id)

    # Check if run belongs to user (or admin)
    if run and not is_admin and run.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    # Also check in-memory runs
    data = repo.get(run_id)
    if data and not is_admin and data.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    if not store.run_exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    store.delete_run(run_id)
    repo.remove(run_id)
    return {"status": "ok", "deleted": run_id}

@router.post("/runs/batch-delete")
async def batch_delete_runs(
    body: BatchDeleteRunsRequest, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Delete multiple persisted run records. Owner/admin only. Running runs skipped."""
    run_ids = body.run_ids
    if not run_ids:
        return {"status": "ok", "deleted": [], "errors": []}
    if len(run_ids) > 100:
        raise HTTPException(status_code=422, detail="Maximum 100 runs per batch delete")

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    deleted: list[str] = []
    errors: list[str] = []

    for rid in run_ids:
        data = repo.get(rid)
        if data and data.get("status") == "running":
            errors.append(rid)
            continue
        if data and not is_admin and data.get("user_id", "default") != user.user_id:
            errors.append(rid)
            continue
        run = store.get_run(rid)
        if run and not is_admin and run.get("user_id", "default") != user.user_id:
            errors.append(rid)
            continue
        if not store.run_exists(rid):
            errors.append(rid)
            continue
        store.delete_run(rid)
        repo.remove(rid)
        deleted.append(rid)

    return {"status": "ok", "deleted": deleted, "errors": errors}

@router.get("/runs")
async def list_runs(
    request: Request,
    workflow_name: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    store: RunStoreInterface = Depends(get_run_store_dep),
    repo: WorkflowRepository = Depends(get_repository_dep),
):
    """List persisted runs (summary only), merged with currently-running in-memory workflows.

    Only returns runs for the current user (admin sees all).
    """
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    result = store.list_runs(
        workflow_name=workflow_name,
        include_batch=True,
        user_id=None if is_admin else user.user_id,
        summary_only=True,
        limit=limit,
        offset=offset,
    )

    persisted = result["runs"]
    persisted_ids = {r.get("run_id") for r in persisted}

    # Add running in-memory workflows that aren't yet persisted
    live_records = []
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
            "status": "running",
            "inputs": data.get("inputs", {}),
            "created_at": data.get("created_at", ""),
        })

    # Live runs first (most recent), then persisted (sorted by created_at desc by RunStore)
    return {"runs": live_records + persisted, "total": result["total"] + len(live_records), "has_more": result["has_more"]}

@router.get("/runs/{run_id}", response_model=RunDetail, response_model_by_alias=True)
async def get_run(
    run_id: str, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> RunDetail | Response:
    """Get a run by id — persisted disk record or live in-memory workflow.

    Honors ``If-Modified-Since``: if the persisted record hasn't been
    written since the client's last fetch, returns 304 with no body. This
    makes switching back to a previously-viewed run near-instant. Live
    (in-memory) workflows always return fresh data.
    """
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    # Cheap conditional GET for the persisted path
    mtime = store.get_run_mtime(run_id)
    last_modified, not_modified = _check_not_modified(request, mtime)
    if not_modified:
        # Quick authorization check before honoring the 304 — don't leak
        # existence to non-owners. get_run is what we'd call anyway; the
        # check is cheap when the run is absent (no file to read).
        existing = store.get_run(run_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if not is_admin and existing.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        return Response(
            status_code=304,
            headers={"Last-Modified": last_modified} if last_modified else None,
        )

    # 200 path: stamp Last-Modified on the response so the client can 304
    # on subsequent fetches. Use a JSONResponse so we control headers.
    run = store.get_run(run_id)
    if run:
        if not is_admin and run.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        body = _persisted_run_detail(run)
        if last_modified:
            from fastapi.responses import JSONResponse
            return JSONResponse(content=body, headers={"Last-Modified": last_modified})
        return body

    # Fall back to in-memory live workflow
    data = repo.get(run_id)
    if data is not None:
        if not is_admin and data.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        return _live_run_detail(run_id, data, repo)

    raise HTTPException(status_code=404, detail="Run not found")

@router.get("/runs/{run_id}/charts")
async def get_run_charts(
    run_id: str, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
) -> dict | None:
    """Load chart_groups sidecar data for a persisted run (lazy loading)."""
    store, run, user, is_admin = _load_run_for_user(run_id, request, store)
    return store.get_charts(run_id)

@router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: str, request: Request, since: float | None = None, limit: int | None = None,
    store: RunStoreInterface = Depends(get_run_store_dep),
) -> list[dict] | None:
    """Events sidecar. `since` filters ts>=since; `limit` caps the slice."""
    store, run, user, is_admin = _load_run_for_user(run_id, request, store)
    events = store.get_events(run_id)
    if events is None:
        return None
    if since is not None:
        events = [e for e in events if (e.get("ts") or 0) >= since]
    return events[:limit] if (limit is not None and limit >= 0) else events

@router.get("/runs/{run_id}/outline")
async def get_run_outline(
    run_id: str, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
) -> list[dict] | None:
    """Pre-computed per-(nodeId, iter) outline summary. None = legacy / failed → frontend derives from conversation."""
    store, run, user, is_admin = _load_run_for_user(run_id, request, store)
    return store.get_outline(run_id)

@router.get("/runs/{run_id}/snapshot")
async def get_run_snapshot(
    run_id: str, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
) -> dict | None:
    """Latest-state snapshot for O(1) frontend refresh (long-run replay).

    Returns a self-contained payload: status / dag / agent_io / conversation /
    charts / todo_states / nodes_latest / seq_cursor. Frontend hydrates all
    scoped stores from this single response, then WS-subscribes from
    seq_cursor onwards — no full buffer replay.

    None = legacy / never written → frontend falls back to legacy replay
    path (bus.subscribe(since_seq=0)).

    See docs/plans/2026-06-16-long-run-replay-architecture.md.
    """
    store, run, user, is_admin = _load_run_for_user(run_id, request, store)
    return store.get_snapshot(run_id)

@router.get("/runs/{run_id}/conversation")
async def get_run_conversation(
    run_id: str, request: Request,
    before: int | None = None, limit: int = 50,
    store: RunStoreInterface = Depends(get_run_store_dep),
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Windowed conversation slice. before=exclusive upper bound on array index."""
    limit = max(1, min(limit, 200))
    conv = _load_conversation_for_user(run_id, request, store, repo)
    total = len(conv)
    upper = total if before is None else max(0, min(before, total))
    start = max(0, upper - limit)
    return {"messages": conv[start:upper], "has_more": start > 0, "total": total}

@router.patch("/runs/{run_id}/conversation")
async def update_run_conversation(
    run_id: str, body: UpdateRunConversationRequest, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Update conversation messages for a run — persisted or in-memory."""
    conversation = body.conversation

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    # Try persisted run first
    run = store.get_run(run_id)
    if run:
        if not is_admin and run.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        store.save_conversation(run_id, conversation)
        return {"status": "ok"}

    # For in-memory running workflows, store conversation in repository
    data = repo.get(run_id)
    if data is not None:
        if not is_admin and data.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        data["conversation"] = conversation
        return {"status": "ok"}

    raise HTTPException(status_code=404, detail="Run not found")

@router.patch("/runs/{run_id}/charts")
async def update_run_charts(
    run_id: str, body: UpdateRunChartsRequest, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
) -> dict:
    """Update chart_groups snapshot for a persisted run (so Results tab replays)."""
    store, _run, _user, _is_admin = _load_run_for_user(run_id, request, store)
    store.save_charts(run_id, body.chart_groups)
    return {"status": "ok"}

# ── Follow-up session persistence ────────────────────────────────────────

@router.patch("/runs/{run_id}/followup")
async def update_run_followup(
    run_id: str, body: UpdateRunFollowupRequest, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
) -> dict:
    """Persist a follow-up session for a specific agent."""
    store, _run, _user, _is_admin = _load_run_for_user(run_id, request, store)

    from datetime import datetime, timezone
    session_data = {
        "model": body.model,
        "messages": body.messages,
        "turn_count": body.turn_count,
        "created_at": body.created_at or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    store.update_followup(run_id, body.agent_name, session_data)
    return {"status": "ok"}

@router.delete("/runs/{run_id}/followup/{agent_name}")
async def delete_run_followup(
    run_id: str,
    agent_name: str,
    request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
) -> dict:
    """Clear a follow-up session for a specific agent."""
    store, _run, _user, _is_admin = _load_run_for_user(run_id, request, store)

    from harness.followup import get_followup_manager
    get_followup_manager().clear(run_id, agent_name)
    store.delete_followup(run_id, agent_name)
    return {"status": "ok"}

@router.get("/runs/{run_id}/checkpoints", response_model=list[CheckpointInfo])
async def list_checkpoints(
    run_id: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> list[CheckpointInfo]:
    """List all checkpoints for a workflow run."""
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
    run_id: str, body: ResumeRequest, req: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
    store: RunStoreInterface = Depends(get_run_store_dep),
    runner: WorkflowRunner = Depends(get_runner_dep),
) -> dict:
    """Resume a workflow from a checkpoint.

    If checkpoint_id is not provided, resumes from the latest non-final
    checkpoint. After a process restart, reconstructs the Workflow from
    the persisted disk record and resumes from the last checkpoint.
    """
    if not repo.contains(run_id):
        # Cross-restart: try to reconstruct from disk record
        disk_record = store.get_run(run_id)
        if disk_record is None:
            raise HTTPException(status_code=404, detail="Run not found")

        # Only reconstruct paused runs
        if disk_record.get("status") != "paused":
            raise HTTPException(status_code=404, detail="Run not found")

        _reconstruct_run_to_repo(repo, run_id, disk_record, req)

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

    # Ensure checkpointer is set (needed for reconstructed workflows after restart)
    if workflow.checkpointer is None:
        checkpoint_mgr = get_checkpoint_manager()
        workflow.checkpointer = await checkpoint_mgr.get_checkpointer()

    # Compile if needed (reconstructed workflows are not yet compiled)
    if workflow._compiled is None:
        workflow.compile()

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
            "dag": repo.get_dag(run_id),
            "resumed_from": config["configurable"].get("checkpoint_id"),
            "envelope": workflow.envelope,
            "started_ts_ms": int(time.time() * 1000),
        })

    # Submit resume to runner
    guidance = body.guidance
    await runner.submit(
        run_id, workflow, data.get("inputs", {}), event_bus,
        config=config, resume=True, user_id=run_user_id,
        work_dir=data.get("work_dir"),
        guidance=guidance,
    )

    return {
        "workflow_id": run_id,
        "status": "running",
        "resumed_from": config["configurable"].get("checkpoint_id"),
    }

@router.post("/runs/{run_id}/rerun", response_model=CreateWorkflowResponse)
async def rerun(
    run_id: str, request: Request,
    store: RunStoreInterface = Depends(get_run_store_dep),
    repo: WorkflowRepository = Depends(get_repository_dep),
    runner: WorkflowRunner = Depends(get_runner_dep),
) -> CreateWorkflowResponse:
    """Re-run a previous run with the same workflow config and inputs."""
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    if not is_admin and run.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    # Block concurrent workflows at capacity
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
        Agent.from_dict({
            "name": a["name"],
            "after": a.get("after"),
            "tools": a.get("tools"),
            "model": a.get("model"),
            "retries": a.get("retries", 3),
            "on_pass": a.get("on_pass"),
            "on_fail": a.get("on_fail"),
            "eval": a.get("eval", False),
            "result_type_name": a.get("result_type_name"),
            "result_type_schema": a.get("result_type_schema"),
        })
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
            "envelope": workflow.envelope,
            "started_ts_ms": int(time.time() * 1000),
        })

    run_config = {"configurable": {"thread_id": new_id}}
    await runner.submit(new_id, workflow, inputs, event_bus, config=run_config, user_id=user.user_id)

    return CreateWorkflowResponse(
        workflow_id=new_id,
        status="running",
        dag=dag_struct,
    )
