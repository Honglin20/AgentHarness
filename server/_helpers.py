"""Shared helpers used by multiple routers.

These functions don't belong to any single domain router — they're
shared infrastructure (validation, workflow lifecycle, bus creation,
benchmark enrichment, etc.).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from harness.api import Agent, DEFAULT_EXECUTOR, Workflow, _WORKFLOWS_DIR

if TYPE_CHECKING:
    from harness.run_store_interface import RunStoreInterface
    from server.repository import WorkflowRepository
from harness.compiler.dag_builder import build_dag
from harness.compiler.md_parser import _SHARED_AGENTS_DIR
from harness.tools.registry import ToolRegistry
from harness.user_manager import get_current_user, get_user_manager
from server.repository import get_repository
from server.schemas import (
    AgentDef,
    CreateWorkflowResponse,
    HealthResponse,
)

logger = logging.getLogger(__name__)


def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse()


def _validate_workflow_dir(workflow: str, user_id: str | None = None) -> Path:
    """Validate a workflow folder name and return its absolute path.

    Search order（与 ``list_saved_workflows`` 保持一致，避免 PATCH 写一处
    POST 读另一处的契约错位）:
      1. workflows/_shared/workflows/{workflow}/
      2. workflows/users/{user_id}/workflows/{workflow}/
      3. workflows/{workflow}/ (legacy)
      4. Registry (builtin + project + extra registrations) — 仅当文件系统
         查找全部失败时才回退到 registry，避免 project-scope 的 legacy
         副本覆盖 shared 上的同名 workflow（用户 PATCH 写盘但启动 run 读
         到旧副本的根因）。

    Args:
        workflow: Workflow name
        user_id: Optional user ID for private workflows

    Rejects path traversal. The directory does not need to exist (caller decides).

    Note: ``_WORKFLOWS_DIR`` is resolved dynamically from ``harness.workflow``
    so tests that monkey-patch ``harness.workflow._WORKFLOWS_DIR`` take effect.
    """
    if not workflow or "/" in workflow or "\\" in workflow or workflow.startswith("."):
        raise HTTPException(status_code=400, detail="invalid workflow name")

    # Re-read each call via the compatibility getter — tests historically
    # patched harness.api._WORKFLOWS_DIR (legacy binding), newer tests patch
    # harness.workflow._WORKFLOWS_DIR. The getter honors both.
    import harness.workflow as _wf_mod
    workflows_root = _wf_mod._get_workflows_dir()

    # 1. Try shared workflows first
    shared_path = (workflows_root / "_shared" / "workflows" / workflow).resolve()
    if str(shared_path).startswith(str(workflows_root.resolve())) and (shared_path / "workflow.json").exists():
        return shared_path

    # 2. Try user's private workflows
    if user_id and user_id != "default":
        private_path = (workflows_root / "users" / user_id / "workflows" / workflow).resolve()
        if str(private_path).startswith(str(workflows_root.resolve())) and (private_path / "workflow.json").exists():
            return private_path

    # 3. Legacy: workflows/{workflow}/ (root-level, not under _shared)
    legacy_path = (workflows_root / workflow).resolve()
    if str(legacy_path).startswith(str(workflows_root.resolve())) and (legacy_path / "workflow.json").exists():
        return legacy_path

    # 4. Registry fallback (builtin + project resources) — 仅当文件系统
    # 查找全部失败时才用，保证 PATCH 写盘的文件就是 POST 启动 run 时读的文件。
    from harness.registry import get_registry
    try:
        return get_registry().resolve_workflow(workflow).resource_dir
    except FileNotFoundError:
        pass

    # Final fallback: 返回 legacy 路径（即便 workflow.json 不存在）。
    # 兼容 ad-hoc 启动场景：workflow_name 是临时拼的字符串，没有 workflow.json。
    resolved = (workflows_root / workflow).resolve()
    if not str(resolved).startswith(str(workflows_root.resolve())):
        raise HTTPException(status_code=400, detail="workflow escapes workflows root")
    return resolved


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


def _check_not_modified(request, mtime):
    """Conditional GET helper for run detail endpoints.

    Returns ``(Last-Modified header value, not_modified_flag)``. The flag
    is True when the client's ``If-Modified-Since`` indicates they already
    have the latest version — caller should return a 304. Imported here so
    every run / charts / events handler can use the same logic without
    each router copy-pasting ~15 lines.
    """
    from email.utils import formatdate, parsedate_to_datetime

    if mtime is None:
        return None, False
    last_modified = formatdate(mtime, usegmt=True)
    ims = request.headers.get("If-Modified-Since") or request.headers.get("if-modified-since")
    if not ims:
        return last_modified, False
    try:
        ims_ts = parsedate_to_datetime(ims).timestamp()
    except (TypeError, ValueError):
        return last_modified, False
    # Compare at 1s precision (HTTP dates have 1s resolution; truncate mtime)
    return last_modified, ims_ts >= int(mtime)


def _build_conversation_from_run(
    run: dict,
    run_id: str,
    store: RunStoreInterface,
) -> list[dict]:
    """Build conversation on-the-fly from agent_io + per-iter sidecars.

    v3 (ADR: single-source-streaming-state D3). After D4 removed conversation
    from run_record, this is the canonical reconstruction path. Aggregates
    every (node, iter) sidecar so multi-iter agents + thinking /
    tool_streaming_outputs are preserved (the legacy agent_io-only path
    loses them both).

    Returns an empty list when agent_io is empty (run hasn't started yet).
    """
    from harness.extensions.collectors import build_conversation

    agent_io = run.get("agent_io") or {}
    if not agent_io:
        return []

    iter_index: dict = {}
    try:
        iter_index = store.get_iter_index(run_id) or {}
    except Exception:
        logger.warning("get_iter_index failed for %s — falling back to agent_io only", run_id, exc_info=True)

    sidecar_data: dict[str, list[dict]] = {}
    invocation_counts: dict[str, int] = {}
    for node_id, entries in iter_index.items():
        if not isinstance(entries, list):
            continue
        sidecars: list[dict] = []
        node_iters: list[int] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            iter_num = entry.get("iter")
            if not isinstance(iter_num, int):
                continue
            try:
                sidecar = store.get_iter_sidecar(run_id, node_id, iter_num)
            except Exception:
                sidecar = None
            if sidecar:
                sidecars.append(sidecar)
                node_iters.append(iter_num)
        if sidecars:
            sidecar_data[node_id] = sidecars
        if node_iters:
            invocation_counts[node_id] = max(node_iters)

    return build_conversation(
        agent_io,
        invocation_counts=invocation_counts or None,
        sidecar_data=sidecar_data or None,
    )


def _load_conversation_for_user(
    run_id: str,
    request: Request,
    store: RunStoreInterface,
    repo: WorkflowRepository,
) -> list[dict]:
    """Auth-checked full conversation list (persisted or in-memory repo).

    Used by GET /runs/{id}/conversation to slice cursor windows. Raises
    404 (run absent) or 403 (caller is not the owner and not admin).

    v3 (ADR D3): for persisted runs without a stored conversation field
    (D4 removed it from run_record), reconstruct on-the-fly from agent_io +
    per-iter sidecars via ``_build_conversation_from_run``. This preserves
    thinking / tool_streaming_outputs / multi-iter history that the old
    agent_io-only path lost.
    """
    user = get_current_user(request)
    is_admin = get_user_manager().is_admin(user)
    run = store.get_run(run_id)
    if run:
        if not is_admin and run.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        conv = run.get("conversation") or []
        if conv:
            # Legacy run record with stored conversation — return as-is.
            return conv
        # D4 path: build on-the-fly from agent_io + sidecars (preserves v3 fields).
        return _build_conversation_from_run(run, run_id, store)
    data = repo.get(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not is_admin and data.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")
    return data.get("conversation") or []


def _persisted_run_detail(run: dict) -> dict:
    """Serialize a persisted run record into the RunDetail response shape.

    chart_groups, events, and conversation are intentionally None — they can
    be very large for long workflows, so they load lazily via dedicated GET
    endpoints. _has_* flags tell the client whether to bother fetching.
    """
    conv = run.get("conversation") or []
    agent_io = run.get("agent_io") or {}
    # v3 (ADR D3): _has_conversation is True when EITHER legacy stored
    # conversation OR agent_io is present (the latter means sidecar-driven
    # build_conversation can reconstruct it on demand). D4 removed
    # conversation from run_record, so the agent_io signal is what makes
    # the frontend actually fetch /runs/{id}/conversation for new runs.
    has_conversation = bool(conv) or bool(agent_io)
    return {
        "run_id": run.get("run_id"),
        "workflow_name": run.get("workflow_name"),
        "agents_snapshot": run.get("agents_snapshot", []),
        "status": run.get("status"),
        "inputs": run.get("inputs", {}),
        "result": run.get("result"),
        "conversation": None,
        "created_at": run.get("created_at", ""),
        "dag": run.get("dag"),
        "chart_groups": None,
        "agent_io": run.get("agent_io"),
        "events": None,
        "work_dir": run.get("work_dir"),
        "batch_id": run.get("batch_id"),
        "user_id": run.get("user_id"),
        "followup_sessions": run.get("followup_sessions"),
        "_has_charts": run.get("_has_charts", False),
        "_has_events": run.get("_has_events", False),
        "_has_conversation": has_conversation,
        "_has_outline": run.get("_has_outline", False),
        "todo_steps": run.get("todo_steps"),
    }


def _live_run_detail(run_id: str, data: dict, repo) -> dict:
    """Serialize an in-memory (live) workflow into the RunDetail shape."""
    workflow = data["workflow"]
    conv = data.get("conversation") or []
    return {
        "run_id": run_id,
        "workflow_name": workflow.name,
        "agents_snapshot": data.get("agents_snapshot", []),
        "status": data["status"],
        "inputs": data.get("inputs", {}),
        "result": data.get("result"),
        "conversation": None,
        "created_at": data.get("created_at", ""),
        "dag": repo.get_dag(run_id),
        "chart_groups": None,
        "agent_io": None,
        "events": None,
        "work_dir": data.get("work_dir"),
        "batch_id": data.get("batch_id"),
        "user_id": data.get("user_id"),
        "followup_sessions": None,
        "_has_charts": False,
        "_has_events": False,
        "_has_conversation": len(conv) > 0,
        "_has_outline": False,
    }


async def _create_and_start_workflow(
    name: str,
    agents_defs: list[AgentDef] | None,
    workflow_name: str,
    inputs: dict,
    batch_id: str | None = None,
    work_dir: str | None = None,
    user_id: str | None = None,
    request_limit: int | None = None,
) -> CreateWorkflowResponse:
    """Core logic: create a Workflow, compile it, and submit to runner.

    Shared by create_workflow (single run), create_batch (batch run), and
    run_benchmark. Creates an isolated Bus per workflow for concurrency safety.

    agents 真相源是 workflow.json。wf_json_path 存在时完全用盘上 agents 定义
    （scoped workflow 路径，含 PATCH 写入的 executor 等字段）；不存在时
    fallback 到 agents_defs（ad-hoc 入口，POST body 自带 agents）。
    """
    workflow_id = str(uuid.uuid4())

    # Each workflow gets its own Bus — fully isolated events + extensions
    event_bus = _new_bus()

    # Resolve workflow dir and load full agent definitions from workflow.json.
    wf_dir = _validate_workflow_dir(workflow_name, user_id)
    wf_json_path = wf_dir / "workflow.json"

    if wf_json_path.exists():
        # 盘驱动：scoped workflow 路径。完全用 workflow.json 上的 agents 定义，
        # 忽略 POST body 的 agents_defs。PATCH 写入的 executor 等字段天然保留。
        try:
            disk_agents_list = json.loads(
                wf_json_path.read_text(encoding="utf-8")
            ).get("agents", [])
        except Exception:
            raise HTTPException(
                status_code=500,
                detail=f"workflow.json corrupted at {wf_json_path}",
            )
        agents = [Agent.from_dict(a) for a in disk_agents_list]
    else:
        # ad-hoc fallback：无盘可读（旧 WorkflowLauncher 入口）。
        # agents_defs 必须由调用方提供，否则 fail loud。
        if not agents_defs:
            raise HTTPException(
                status_code=400,
                detail=f"workflow '{workflow_name}' has no workflow.json and no agents provided",
            )
        agents = [Agent.from_dict(a.model_dump()) for a in agents_defs]

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
        request_limit=request_limit,
    )

    from harness.extensions.eval import EvalJudge

    has_eval = any(a.eval for a in agents)
    if has_eval:
        # Runtime fallback: API callers can POST eval=true directly without
        # having gone through Workflow.compile() + save() first.
        import os
        judge_model = os.environ.get("HARNESS_MODEL", "")
        if not judge_model:
            raise HTTPException(
                status_code=400,
                detail="LLM model not configured. Set HARNESS_MODEL in Settings to use the eval feature.",
            )
        workflow.use(EvalJudge(max_retries=2))
        for mutator in event_bus.get_mutators():
            mutator.mutate(workflow)
        # Clear flags so downstream compile() doesn't try to re-materialize/persist
        for a in workflow.agents:
            if getattr(a, "eval", False):
                a.eval = False

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
        "envelope": workflow.envelope,
        "started_ts_ms": int(time.time() * 1000),
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


def _get_benchmark_store():
    """Return the singleton BenchmarkStore."""
    from harness.benchmark_store import BenchmarkStore
    return BenchmarkStore()


def _enrich_benchmark_result(
    result: dict,
    repo,
    store=None,
    benchmark_name: str = "",
    scoring_config: dict | None = None,
    historical_baseline: dict | None = None,
) -> None:
    """Enrich a benchmark result with live scores, charts, and status from the repository.

    Persists enriched data back to disk so it survives server restarts.
    When no eval score is found, computes an efficiency score from duration/tokens.
    """
    from harness.scoring.efficiency import EfficiencyScorer

    task_results = result.get("task_results", [])
    changed = False
    scores = []

    # Build efficiency scorer if scoring config exists
    scoring_cfg = scoring_config or {}
    scorer = EfficiencyScorer(
        weights=scoring_cfg.get("weights"),
        thresholds=scoring_cfg.get("thresholds"),
    )
    baseline = historical_baseline or {}

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
            tr["score_source"] = "eval"
            scores.append(score)
            changed = True

        # Extract duration + token_usage from trace (sum across all agents)
        trace = wf_result.get("trace", [])
        total_duration = 0
        total_input = 0
        total_output = 0
        for entry in trace:
            dur = entry.get("duration_ms")
            if dur:
                total_duration += dur
            tu = entry.get("token_usage")
            if tu and isinstance(tu, dict):
                total_input += tu.get("input", 0)
                total_output += tu.get("output", 0)
        if total_duration and not tr.get("duration_ms"):
            tr["duration_ms"] = total_duration
            changed = True
        if total_input or total_output:
            tr["token_usage"] = {"input": total_input, "output": total_output, "total": total_input + total_output}
            changed = True

        # If no eval score and no LLM judge score, compute efficiency score
        if score is None and tr.get("score_source") != "llm_judge" and tr.get("status") in ("completed", "failed"):
            task_baseline = baseline.get(tr.get("task_id", ""))
            eff = scorer.score_task(tr, task_baseline)
            tr["score"] = eff["score"]
            tr["score_breakdown"] = eff["breakdown"]
            tr["score_source"] = eff["score_source"]
            scores.append(eff["score"])
            changed = True
        elif score is None and tr.get("score_source") == "llm_judge" and tr.get("score") is not None:
            # Preserve existing LLM judge score in the average
            scores.append(tr["score"])

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


def _compute_run_averages(result: dict) -> dict:
    """Compute per-run average metrics from task_results. Always returns all fields."""
    scores = []
    durations = []
    costs = []
    tokens = []

    for tr in result.get("task_results", []):
        score = tr.get("score")
        if score is not None:
            scores.append(score)
        dur = tr.get("duration_ms")
        if dur:
            durations.append(dur)
        cost = tr.get("cost_usd")
        if cost is not None:
            costs.append(cost)
        tu = tr.get("token_usage")
        if tu and isinstance(tu, dict):
            tokens.append(tu.get("total", 0))

    return {
        "avg_score": sum(scores) / len(scores) if scores else 0,
        "avg_cost": sum(costs) / len(costs) if costs else 0,
        "avg_duration_ms": sum(durations) / len(durations) if durations else 0,
        "avg_tokens": sum(tokens) / len(tokens) if tokens else 0,
    }


def _reconstruct_run_to_repo(repo, run_id: str, record: dict, request: Request) -> None:
    """Reconstruct a Workflow from a persisted run record and inject into the in-memory repo.

    Called when resume_run() finds the run on disk but not in the repo
    (e.g., after process restart).
    """
    from harness.api import Agent, Workflow
    from harness.tools.registry import ToolRegistry
    from server.runner import _build_agents_snapshot
    from datetime import datetime, timezone

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    if not is_admin and record.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    workflow_name = record["workflow_name"]
    agents_snapshot = record.get("agents_snapshot", [])
    work_dir = record.get("work_dir")

    # Reconstruct agents from snapshot (includes on_pass/on_fail/eval).
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
            "executor": a.get("executor", DEFAULT_EXECUTOR),
        })
        for a in agents_snapshot
        if not a["name"].startswith("_judge_") and "_passthrough" not in a["name"]
    ]

    # Resolve workflow dir
    user_id = user.user_id if user.user_id != "default" else None
    try:
        wf_dir = _validate_workflow_dir(workflow_name, user_id)
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow definition for '{workflow_name}' not found — "
                   f"restore the workflow directory before resuming this run.",
        )

    # Create fresh Bus
    event_bus = _new_bus()

    # Create workflow (checkpointer injected later in resume_run)
    workflow = Workflow(
        name=workflow_name,
        agents=agents,
        workflow_dir=wf_dir,
        tool_registry=ToolRegistry(),
        event_bus=event_bus,
    )

    # Auto-register extensions
    from harness.extensions.eval import EvalJudge
    if any(a.eval for a in agents):
        workflow.use(EvalJudge(max_retries=2))

    # Store in repo
    dag = record.get("dag")
    repo.put(run_id, {
        "workflow": workflow,
        "status": "paused",
        "result": record.get("result"),
        "inputs": record.get("inputs", {}),
        "thread_id": run_id,
        "created_at": record.get("created_at", datetime.now(timezone.utc).isoformat()),
        "agents_snapshot": _build_agents_snapshot(workflow),
        "event_bus": event_bus,
        "user_id": record.get("user_id"),
        "work_dir": work_dir,
    })
    if dag:
        repo.put_dag(run_id, dag)
