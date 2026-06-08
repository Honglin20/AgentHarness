"""Workflow lifecycle endpoints (definitions, create, cancel, status, dag, trace)."""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from harness.api import Workflow
from harness.user_manager import get_current_user, get_user_manager
from server._helpers import (
    _check_workflow_owner,
    _create_and_start_workflow,
    _get_bus_for_workflow,
)
from server.dependencies import (
    get_repository_dep,
    get_runner_dep,
)
from server.repository import WorkflowRepository
from server.runner import WorkflowRunner
from server.schemas import (
    CreateBatchRequest,
    CreateBatchResponse,
    CreateWorkflowRequest,
    CreateWorkflowResponse,
    BatchRunSummary,
    WorkflowStatusResponse,
)

router = APIRouter()


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


@router.post("/workflows", response_model=CreateWorkflowResponse)
async def create_workflow(
    request_obj: CreateWorkflowRequest,
    request: Request,
    runner: WorkflowRunner = Depends(get_runner_dep),
) -> CreateWorkflowResponse:
    """Create and start a single workflow."""
    user = get_current_user(request)

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
    request_obj: CreateBatchRequest,
    request: Request,
    runner: WorkflowRunner = Depends(get_runner_dep),
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> CreateBatchResponse:
    """Create and start a batch of workflow runs with different inputs.

    Each item in `items` becomes an independent workflow run.
    All runs share the same workflow definition (agents + prompts).
    Each run gets its own isolated Bus.
    """
    user = get_current_user(request)

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
            work_dir=request_obj.work_dir,
            user_id=user.user_id,
        )
        runs.append(BatchRunSummary(
            workflow_id=result.workflow_id,
            label=item.label,
            status="running",
        ))

    # Store batch metadata
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
async def get_batch_status(
    batch_id: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> CreateBatchResponse:
    """Get the status of all runs in a batch."""
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


@router.get("/workflows/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow(
    workflow_id: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> WorkflowStatusResponse:
    """Get workflow status and result."""
    if not repo.contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = repo.get(workflow_id)
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
async def cancel_workflow(
    workflow_id: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
    runner: WorkflowRunner = Depends(get_runner_dep),
) -> dict:
    """Pause a running workflow. Status becomes 'paused' and can be resumed."""
    if not repo.contains(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = repo.get(workflow_id)
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    if not is_admin and data.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your workflow")

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
async def get_workflow_dag(
    workflow_id: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Get DAG structure for React Flow."""
    dag = repo.get_dag(workflow_id)
    if dag is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    _check_workflow_owner(workflow_id, request)
    return dag


@router.get("/workflows/{workflow_id}/trace")
async def get_workflow_trace(
    workflow_id: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Get execution trace."""
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
