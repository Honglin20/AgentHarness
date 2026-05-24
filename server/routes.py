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
    RunBenchmarkRequest,
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


async def _create_and_start_workflow(
    name: str,
    agents_defs: list[AgentDef],
    workflow_name: str,
    inputs: dict,
    event_bus,
    batch_id: str | None = None,
) -> CreateWorkflowResponse:
    """Core logic: create a Workflow, compile it, and submit to runner.

    Shared by create_workflow (single run) and create_batch (batch run).
    """
    workflow_id = str(uuid.uuid4())

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

    wf_dir = _validate_workflow_dir(workflow_name)

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
        workflow.use(EvalJudge(max_retries=2))

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
    })

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
    dag = {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges}
    repo.put_dag(workflow_id, dag)

    event_bus.emit("workflow.started", {
        "workflow_id": workflow_id,
        "name": workflow.name,
        "inputs": inputs,
        "dag": dag,
        "workflow": workflow_name,
        "batch_id": batch_id,
    })

    from server.runner import get_runner
    runner = get_runner()
    run_config = {"configurable": {"thread_id": workflow_id}}
    await runner.submit(workflow_id, workflow, inputs, event_bus, config=run_config)

    return CreateWorkflowResponse(
        workflow_id=workflow_id,
        status="running",
        dag=dag,
    )


@router.post("/workflows", response_model=CreateWorkflowResponse)
async def create_workflow(
    request: CreateWorkflowRequest,
    event_bus = Depends(get_event_bus),
) -> CreateWorkflowResponse:
    """Create and start a single workflow."""
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count >= runner.max_concurrent:
        raise HTTPException(status_code=409, detail=f"Max {runner.max_concurrent} concurrent workflows. Wait for one to finish.")
    if runner.running_count == 0:
        event_bus.clear_buffer()

    if not request.workflow:
        raise HTTPException(status_code=400, detail="workflow is required")

    return await _create_and_start_workflow(
        name=request.name,
        agents_defs=request.agents,
        workflow_name=request.workflow,
        inputs=request.inputs,
        event_bus=event_bus,
    )


@router.post("/batch", response_model=CreateBatchResponse)
async def create_batch(
    request: CreateBatchRequest,
    event_bus = Depends(get_event_bus),
) -> CreateBatchResponse:
    """Create and start a batch of workflow runs with different inputs.

    Each item in `items` becomes an independent workflow run.
    All runs share the same workflow definition (agents + prompts).
    """
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count == 0:
        event_bus.clear_buffer()

    if not request.workflow:
        raise HTTPException(status_code=400, detail="workflow is required")
    if not request.items:
        raise HTTPException(status_code=400, detail="items must not be empty")

    batch_id = str(uuid.uuid4())
    runs: list[BatchRunSummary] = []

    for item in request.items:
        if runner.running_count >= runner.max_concurrent:
            runs.append(BatchRunSummary(
                workflow_id="",
                label=item.label,
                status="pending",
                error="Max concurrent limit reached; queued for later",
            ))
            continue

        result = await _create_and_start_workflow(
            name=request.name,
            agents_defs=request.agents,
            workflow_name=request.workflow,
            inputs=item.inputs,
            event_bus=event_bus,
            batch_id=batch_id,
        )
        runs.append(BatchRunSummary(
            workflow_id=result.workflow_id,
            label=item.label,
            status="running",
        ))

    # Store batch metadata
    repo = get_repository()
    repo.put_batch(batch_id, {
        "batch_id": batch_id,
        "name": request.name,
        "workflow": request.workflow,
        "runs": {r.workflow_id: {"label": r.label, "status": r.status} for r in runs if r.workflow_id},
    })

    return CreateBatchResponse(batch_id=batch_id, runs=runs)


@router.get("/batch/{batch_id}", response_model=CreateBatchResponse)
async def get_batch_status(batch_id: str) -> CreateBatchResponse:
    """Get the status of all runs in a batch."""
    repo = get_repository()
    batch = repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

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
    """List all saved benchmarks."""
    return _get_benchmark_store().list_benchmarks()


@router.post("/benchmarks")
async def create_benchmark(body: BenchmarkDef) -> dict:
    """Create a new benchmark."""
    store = _get_benchmark_store()
    tasks = [t.model_dump() for t in body.tasks]
    path = store.save_benchmark(body.name, tasks, description=body.description)
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
    store.save_benchmark(name, tasks, description=body.description)
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
    event_bus=Depends(get_event_bus),
) -> BenchmarkRunSummary:
    """Run a benchmark with a specific workflow.

    Creates one workflow run per task, tracks progress, and persists results.
    """
    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    # Load workflow definition
    wf_dir = _validate_workflow_dir(body.workflow)
    wf_json = wf_dir / "workflow.json"
    if not wf_json.exists():
        raise HTTPException(status_code=404, detail=f"Workflow '{body.workflow}' not found")
    wf_data = json.loads(wf_json.read_text())
    agents_defs = [AgentDef(**a) for a in wf_data.get("agents", [])]

    # Use batch API to create all runs
    batch_req = CreateBatchRequest(
        name=name,
        agents=agents_defs,
        workflow=body.workflow,
        items=[
            {"label": t["label"], "inputs": t.get("inputs", {"task": t["label"]})}
            for t in bm["tasks"]
        ],
    )
    batch_resp = await create_batch(batch_req, event_bus=event_bus)

    # Build result record
    run_id = batch_resp.batch_id
    from datetime import datetime, timezone
    task_results = []
    for i, run in enumerate(batch_resp.runs):
        task_results.append({
            "task_id": bm["tasks"][i].get("id", f"task_{i + 1}"),
            "label": run.label,
            "status": run.status,
            "workflow_id": run.workflow_id,
        })

    result = {
        "run_id": run_id,
        "benchmark_name": name,
        "workflow_name": body.workflow,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_results": task_results,
    }
    store.save_result(name, result)

    return BenchmarkRunSummary(
        run_id=run_id,
        benchmark_name=name,
        workflow_name=body.workflow,
        status="running",
        created_at=result["created_at"],
        task_results=[],
    )


@router.get("/benchmarks/{name}/results")
async def list_benchmark_results(name: str) -> list[dict]:
    """List all run results for a benchmark."""
    store = _get_benchmark_store()
    results = store.list_results(name)
    if not results and not store.load_benchmark(name):
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return results


@router.get("/benchmarks/{name}/results/{run_id}")
async def get_benchmark_result(name: str, run_id: str) -> dict:
    """Get a specific benchmark run result with aggregated scores."""
    store = _get_benchmark_store()
    result = store.get_result(run_id, benchmark_name=name)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    # Enrich with live status from repository
    repo = get_repository()
    task_results = result.get("task_results", [])
    scores = []
    for tr in task_results:
        wid = tr.get("workflow_id", "")
        if wid:
            data = repo.get(wid)
            if data:
                tr["status"] = data["status"]
                wf_result = data.get("result")
                if wf_result:
                    outputs = wf_result.get("outputs", {})
                    # Extract eval_judge scores from judge node outputs
                    for key, val in outputs.items():
                        if key.startswith("_judge_") and isinstance(val, dict):
                            judgment = val.get("_judgment", {})
                            score = judgment.get("score")
                            if score is not None:
                                tr["score"] = score
                                scores.append(score)
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

    return result


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

    # Block if already at capacity
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count >= runner.max_concurrent:
        raise HTTPException(status_code=409, detail=f"Max {runner.max_concurrent} concurrent workflows. Wait for one to finish.")

    if runner.running_count == 0:
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

    # Block concurrent workflows at capacity
    from server.runner import get_runner
    runner = get_runner()
    if runner.running_count >= runner.max_concurrent:
        raise HTTPException(status_code=409, detail=f"Max {runner.max_concurrent} concurrent workflows. Wait for one to finish.")

    if runner.running_count == 0:
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