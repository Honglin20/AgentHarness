"""Benchmark endpoints (CRUD, run, results, regression, LLM judge)."""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from harness.user_manager import get_current_user, get_user_manager
from server._helpers import (
    _compute_run_averages,
    _create_and_start_workflow,
    _enrich_benchmark_result,
    _get_benchmark_store,
    _validate_workflow_dir,
)
from server.dependencies import get_repository_dep
from server.repository import WorkflowRepository
from server.schemas import (
    AgentDef,
    BenchmarkDef,
    BenchmarkRunSummary,
    BenchmarkTaskResult,
    BatchRunSummary,
    RunBenchmarkRequest,
)

router = APIRouter()


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
    scoring = body.scoring.model_dump(exclude_none=True) if body.scoring else None
    path = store.save_benchmark(body.name, tasks, description=body.description, prep=prep, scoring=scoring)
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
    scoring = body.scoring.model_dump(exclude_none=True) if body.scoring else None
    store.save_benchmark(name, tasks, description=body.description, prep=prep, scoring=scoring)
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
    repo: WorkflowRepository = Depends(get_repository_dep),
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
async def list_benchmark_results(
    name: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> list[dict]:
    """List all run results for a benchmark, enriched with live scores."""
    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    user = get_current_user(request)
    user_mgr = get_user_manager()
    uid = None if user_mgr.is_admin(user) else user.user_id

    results = store.list_results(name, user_id=uid)

    scoring_config = (bm.get("scoring") or {}) if bm else {}
    historical = store.list_results(name)
    from harness.scoring.efficiency import EfficiencyScorer
    baseline = EfficiencyScorer.compute_baseline(historical)
    for result in results:
        _enrich_benchmark_result(result, repo, store, name, scoring_config, baseline)

    return results


@router.get("/benchmarks/{name}/results/{run_id}")
async def get_benchmark_result(
    name: str,
    run_id: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Get a specific benchmark run result with aggregated scores."""
    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    result = store.get_result(run_id, benchmark_name=name)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    scoring_config = (bm.get("scoring") or {}) if bm else {}
    historical = store.list_results(name)
    from harness.scoring.efficiency import EfficiencyScorer
    baseline = EfficiencyScorer.compute_baseline(historical)
    _enrich_benchmark_result(result, repo, store, name, scoring_config, baseline)

    return result


@router.get("/benchmarks/{name}/regression")
async def benchmark_regression(
    name: str,
    baseline_run: str | None = None,
    request: Request = None,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Compare latest benchmark run against a baseline for regressions.

    If baseline_run is not specified, compares against the second-most-recent run.
    """
    from harness.extensions.plugins.regression_detector import detect_regressions

    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    results = store.list_results(name)
    if len(results) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 benchmark runs to compare")

    # Sort by created_at descending (newest first)
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    current_result = results[0]

    if baseline_run:
        baseline_result = store.get_result(baseline_run, benchmark_name=name)
        if not baseline_result:
            raise HTTPException(status_code=404, detail="Baseline run not found")
    else:
        baseline_result = results[1]

    # Enrich both results with live scores
    scoring_config = (bm.get("scoring") or {}) if bm else {}
    all_results = store.list_results(name)
    from harness.scoring.efficiency import EfficiencyScorer
    baseline = EfficiencyScorer.compute_baseline(all_results)
    _enrich_benchmark_result(current_result, repo, store, name, scoring_config, baseline)
    _enrich_benchmark_result(baseline_result, repo, store, name, scoring_config, baseline)

    baseline_avg = _compute_run_averages(baseline_result)
    current_avg = _compute_run_averages(current_result)

    regressions = detect_regressions(baseline_avg, current_avg)

    return {
        "benchmark_name": name,
        "baseline_run_id": baseline_result.get("run_id"),
        "current_run_id": current_result.get("run_id"),
        "baseline": baseline_avg,
        "current": current_avg,
        "regressions": regressions,
    }


@router.post("/benchmarks/{name}/judge/{run_id}")
async def judge_benchmark_run(
    name: str,
    run_id: str,
    request: Request,
    repo: WorkflowRepository = Depends(get_repository_dep),
) -> dict:
    """Run LLM-as-Judge on a specific benchmark run.

    Scores each completed task using an LLM, writes quality_score and
    quality_reasoning back to the result. Optionally overrides the composite
    score if no eval score exists.
    """
    from harness.scoring.llm_judge import judge_task_async

    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    result = store.get_result(run_id, benchmark_name=name)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    scoring_config = (bm.get("scoring") or {}).get("llm_judge") or {}
    model = scoring_config.get("model")
    rubric = scoring_config.get("rubric")

    if result.get("status") == "running":
        raise HTTPException(status_code=409, detail="Benchmark is still running. Wait for it to complete.")

    judged_tasks = []

    for tr in result.get("task_results", []):
        if tr.get("status") != "completed":
            continue

        wid = tr.get("workflow_id", "")
        if not wid:
            continue
        data = repo.get(wid)
        if not data:
            continue

        inputs = data.get("inputs", {})
        wf_result = data.get("result")
        if not wf_result:
            continue

        # Collect agent outputs as text
        outputs = wf_result.get("outputs", {})
        output_parts = []
        for key, val in outputs.items():
            if isinstance(val, str):
                output_parts.append(val)
            elif isinstance(val, dict):
                # Try common fields: summary, result, output, details
                for field in ("summary", "result", "output", "details"):
                    if field in val and isinstance(val[field], str):
                        output_parts.append(val[field])
        agent_output = "\n\n".join(output_parts)
        if not agent_output.strip():
            continue

        task_input = inputs.get("task", inputs)
        try:
            judge_result = await judge_task_async(
                task_label=tr.get("label", ""),
                task_input=task_input,
                agent_output=agent_output,
                rubric=rubric,
                model=model,
            )
        except Exception as e:
            judged_tasks.append({
                "task_id": tr.get("task_id"),
                "status": "error",
                "error": str(e),
            })
            continue

        tr["quality_score"] = judge_result.score
        tr["quality_reasoning"] = judge_result.reasoning

        # Override composite score only if no eval score existed
        prev_source = tr.get("score_source")
        tr["score_source"] = "llm_judge"
        if prev_source != "eval":
            tr["score"] = judge_result.score

        judged_tasks.append({
            "task_id": tr.get("task_id"),
            "label": tr.get("label"),
            "quality_score": judge_result.score,
            "reasoning": judge_result.reasoning[:200],
            "status": "ok",
        })

    # Recompute avg_score
    scores = [tr.get("score") for tr in result.get("task_results", []) if tr.get("score") is not None]
    if scores:
        result["avg_score"] = sum(scores) / len(scores)

    store.save_result(name, result)

    return {
        "benchmark_name": name,
        "run_id": run_id,
        "judged_tasks": judged_tasks,
        "avg_score": result.get("avg_score"),
    }
