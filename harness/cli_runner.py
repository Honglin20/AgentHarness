"""CLI run-with-persistence wrapper.

``harness run`` loads a workflow, runs it headlessly (no server / WS), and
writes the run record to the SAME location the server uses
(``$HARNESS_RUNS_DIR or CWD/runs/``). The frontend ``GET /api/runs`` then
discovers the CLI run with zero frontend changes — the user can replay
CLI-run history in the browser.

Design constraints:
  - Does NOT import ``server.*``. Reuses only ``harness.persistence.run_store``
    and ``harness.extensions.collectors`` (which server also uses).
  - The Bus is injected (Workflow.use triggers it) so default plugins
    (StepCounterPlugin etc.) keep working AND so the post-run Collectors
    can extract conversation + chart_groups from the buffer.
  - The generated ``run_id`` is wired into LangGraph's ``thread_id`` so
    checkpoint state is per-CLI-run, not shared across runs of the same
    workflow name.

Why a separate module instead of refactoring server/runner.py:
  - The plan's incremental guarantee forbids modifying server/. Server's
    WorkflowRunner has concurrent-execution, cancellation, user-isolation,
    and batch-tracking concerns that CLI doesn't need. Sharing the
    persistence tail (``_build_agents_snapshot`` mirror + Collectors + save)
    via this helper leaves server untouched.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from harness.compiler.dag_builder import build_dag
from harness.extensions.bus import Bus
from harness.persistence.run_id import generate_run_id
from harness.extensions.collectors import ChartCollector, ConversationCollector
from harness.extensions.console import ConsoleOutput
from harness.extensions.base import BaseHook
from harness.run_store import get_run_store

if TYPE_CHECKING:
    from harness.core.workflow import Workflow
    from harness.types import WorkflowResult

logger = logging.getLogger(__name__)


def _serialize_outputs(outputs: dict) -> dict:
    """Convert BaseModel instances to dicts for JSON serialization.

    Mirrors ``server/runner.py::_serialize_outputs`` — same logic, kept
    local to avoid importing server.* from the CLI path.
    """
    return {
        k: v.model_dump() if isinstance(v, BaseModel) else v
        for k, v in outputs.items()
    }


def _build_agents_snapshot_for_error(workflow: "Workflow") -> list[dict]:
    """Build agents_snapshot for the workflow.error payload.

    Used only on the failure path — the success path goes through
    ``build_agents_snapshot`` (the public mirror of
    server/runner.py::_build_agents_snapshot). On failure we may not have
    a fully populated workflow state, so this is best-effort: catch
    exceptions and return an empty list so the payload still emits.

    Returned snapshot is sufficient for _lookup_agent_executor to map
    failed_node → executor; richer fields (md_content, result_type_name)
    are omitted because the error path does not need them.
    """
    try:
        snap: list[dict] = []
        for agent_def in getattr(workflow, "agents", []) or []:
            entry = {"name": agent_def.name, "executor": getattr(agent_def, "executor", "pydantic-ai")}
            snap.append(entry)
        return snap
    except Exception:
        logger.debug(
            "agents_snapshot build failed on error path; payload will omit executor field",
            exc_info=True,
        )
        return []


def build_agents_snapshot(workflow: "Workflow") -> list[dict]:
    """Snapshot agent definitions with their current MD content.

    Mirrors ``server/runner.py::_build_agents_snapshot`` (private there).
    Kept here so the CLI path produces a record with the same shape the
    frontend expects. When server is later refactored to share this helper
    (future work, NOT this PR), this function moves to
    ``harness/persistence/agents_snapshot.py`` and both callers import it.
    """
    from harness.compiler.md_parser import AgentNotFoundError, resolve_agent_md
    from harness.schema_utils import result_type_to_schema

    workflow_dir = workflow.workflow_dir
    snapshot: list[dict] = []
    for agent_def in workflow.agents:
        eval_target = getattr(agent_def, "_eval_target", None)
        if eval_target is not None:
            md_content = (
                "---\n"
                "auto_generated: true\n"
                f"target: {eval_target}\n"
                "result_type: ReviewDecision\n"
                "---\n\n"
                "你是一个评测员。你的任务是评估上游 agent 的输出质量。\n"
            )
        elif "_passthrough" in agent_def.name:
            md_content = (
                "---\nauto_generated: true\n---\n\n(passthrough node — no prompt)"
            )
        else:
            md_content = ""
            try:
                md_path = resolve_agent_md(agent_def.name, workflow_dir)
                md_content = md_path.read_text()
            except AgentNotFoundError:
                logger.debug(
                    "Agent %s has no MD file — using empty content", agent_def.name,
                )

        snap: dict = {
            "name": agent_def.name,
            "after": agent_def.after,
            "md_content": md_content,
            "tools": agent_def.tools,
            "model": agent_def.model,
            "retries": agent_def.retries,
            "on_pass": agent_def.on_pass,
            "on_fail": agent_def.on_fail,
            "eval": agent_def.eval if eval_target is None else True,
        }
        if agent_def.result_type is not None:
            schema = result_type_to_schema(agent_def.result_type)
            if schema is not None:
                snap["result_type_name"] = agent_def.result_type.__name__
                snap["result_type_schema"] = schema
        snapshot.append(snap)
    return snapshot


def build_workflow_dag(workflow: "Workflow") -> dict:
    """Build the DAG dict the frontend expects on a run record.

    Mirrors ``server/_helpers.py:344-356`` — same shape so the frontend's
    DAG renderer doesn't need a CLI-specific branch.
    """
    agents = workflow.agents
    node_order = build_dag(agents)
    edges: list[list[str]] = []
    conditional_edges: list[dict] = []
    for a in agents:
        for dep in a.after or []:
            edges.append([dep, a.name])
        if a.on_pass is not None or a.on_fail is not None:
            if a.on_pass is not None:
                conditional_edges.append(
                    {"from": a.name, "to": a.on_pass, "label": "pass"}
                )
            if a.on_fail is not None:
                conditional_edges.append(
                    {"from": a.name, "to": a.on_fail, "label": "fail"}
                )
    return {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges}


async def run_with_persistence(
    workflow: "Workflow",
    inputs: dict,
    output_hook: Optional[BaseHook] = None,
    work_dir: Optional[str] = None,
) -> tuple[str, Optional["WorkflowResult"]]:
    """Run a workflow headlessly and persist the result for frontend replay.

    Flow:
      1. Register ``output_hook`` (default: ``ConsoleOutput``) via
         ``Workflow.use`` — this also injects a Bus if none is set, which
         default plugins + post-run Collectors depend on.
      2. ``cd`` into ``work_dir`` if given (matches server semantics —
         ``get_runs_dir()`` is CWD-relative so this also scopes where
         ``runs/`` lands).
      3. ``setup`` (MCP + compile), wire ``run_id`` into LangGraph's
         ``thread_id``, ``arun``.
      4. Collect conversation + events + charts from the Bus buffer.
      5. ``RunStore.save(...)`` to ``runs/{run_id}.json`` + sidecars.
      6. On exception, emit ``workflow.error`` and persist a record with
         ``status="failed"`` BEFORE re-raising — the caller (cmd_run)
         decides exit code, but the failed run must still be visible in
         history.

    Returns ``(run_id, result)`` on success. On failure, persists the
    failed record then re-raises — callers should let the exception
    propagate to set a non-zero exit code.
    """
    run_id = generate_run_id(workflow.name)

    # 1) Register the output hook (also ensures _event_bus is populated).
    if output_hook is None:
        output_hook = ConsoleOutput()
    workflow.use(output_hook)

    bus: Bus = workflow._event_bus  # type: ignore[assignment]
    # Workflow.use() guarantees _event_bus is non-None after the call, but
    # be defensive in case a future Workflow subclass changes that.
    if bus is None:  # pragma: no cover — defensive
        bus = Bus()
        workflow._event_bus = bus

    # TuiRenderer (and any future hook that subscribes to non-lifecycle
    # events like cycle.end) needs a bus reference. Use duck typing so
    # we don't import the TUI layer here — ConsoleOutput has no
    # attach_bus method and is silently skipped.
    attach_bus = getattr(output_hook, "attach_bus", None)
    if callable(attach_bus):
        attach_bus(bus)

    # Inject workflow reference so the hook can extract DAG topology
    # when it starts. Also duck-typed — ConsoleOutput silently skips.
    set_workflow = getattr(output_hook, "set_workflow", None)
    if callable(set_workflow):
        set_workflow(workflow)
    # Workflow.use() guarantees _event_bus is non-None after the call, but
    # be defensive in case a future Workflow subclass changes that.
    if bus is None:  # pragma: no cover — defensive
        bus = Bus()
        workflow._event_bus = bus

    # 2) chdir to work_dir — same semantics as server. This must be in
    # effect before setup() (MCP filesystem) and before get_runs_dir() is
    # first consulted by RunStore.
    original_cwd: Optional[str] = None
    if work_dir:
        work_path = Path(work_dir).resolve()
        if str(work_path) != "/":
            for forbidden in ("/etc", "/proc", "/sys", "/root", "/var"):
                if str(work_path).startswith(forbidden):
                    raise RuntimeError(f"Work directory cannot be under {forbidden}")
        if not work_path.exists():
            raise RuntimeError(f"Work directory does not exist: {work_dir}")
        if not work_path.is_dir():
            raise RuntimeError(f"Work path is not a directory: {work_dir}")
        original_cwd = os.getcwd()
        os.chdir(work_path)

    config = {"configurable": {"thread_id": run_id}}

    try:
        # 3) MCP setup + compile + run. workflow_id on builder is needed for
        # LangGraph interrupt support (workflows using langgraph.types.interrupt
        # rather than ask_user).
        await workflow.setup(work_dir=work_dir)
        if workflow._builder is not None:
            workflow._builder.workflow_id = run_id
            if hasattr(workflow._builder, "register_active"):
                workflow._builder.register_active()

        # Register in server.repository so the per-node incremental-save
        # pipeline (_save_incremental in harness/engine/incremental_save.py)
        # can resolve this workflow and emit per-iter sidecars + outline +
        # snapshot. Without this, _save_incremental silently no-ops at
        # `repo.get(wid)` and the frontend sees a run with no iter_index /
        # outline / per-iter sidecars.
        # See docs/refactor/single-source-index-driven/ (Phase 1+2 ADR).
        from datetime import datetime, timezone
        from server.repository import get_repository
        dag = build_workflow_dag(workflow)
        repo = get_repository()
        repo.put(run_id, {
            "workflow": workflow,
            "status": "running",
            "result": None,
            "inputs": inputs,
            "thread_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "agents_snapshot": build_agents_snapshot(workflow),
            "batch_id": None,
            "event_bus": bus,
            "user_id": None,
            "work_dir": work_dir,
        })
        repo.put_dag(run_id, dag)

        # Emit workflow.started BEFORE arun so it lands at the head of the
        # event stream — server does this in _helpers.py:358, and the
        # frontend uses it to initialize UI state (DAG, inputs, envelope).
        # Without it, replay falls back to the run record's static fields,
        # which works but isn't byte-for-byte parity with server runs.
        import time as _time
        bus.emit(
            "workflow.started",
            {
                "workflow_id": run_id,
                "name": workflow.name,
                "workflow": workflow.name,
                "inputs": inputs,
                "dag": dag,
                "envelope": getattr(workflow, "envelope", None),
                "started_ts_ms": int(_time.time() * 1000),
            },
        )

        # arun_workflow now dispatches on_workflow_start/end hooks on the
        # bus (engine fix in this commit). TuiRenderer.on_workflow_start
        # starts Live; on_workflow_end stops it. No explicit start signal
        # needed from cli_runner anymore.
        result = await workflow.arun(inputs, config=config)
        status = "completed"
        error: Optional[str] = None

    except Exception as e:
        status = "failed"
        error = str(e)
        result = None
        # P2-T7: Emit workflow.error with the SAME rich payload schema as
        # server/runner.py so frontend (replay of CLI runs) + CLI sinks
        # both render the full failure context (stderr_tail / phase /
        # executor / failed_node / etc.). Previously CLI emitted a
        # 2-field payload — frontend saw "error" string but missed WHY.
        from harness.engine.error_event import build_workflow_error_payload
        error_payload = build_workflow_error_payload(
            workflow_id=run_id,
            user_id=None,
            error=e,
            agents_snapshot=_build_agents_snapshot_for_error(workflow),
            bus_buffer=getattr(bus, "buffer", []),
        )
        # CLI runs don't track batch_id; keep the original contract by
        # not setting batch_id (helper omits it when None).
        bus.emit("workflow.error", error_payload)

    finally:
        # MCP cleanup is best-effort. During asyncio.run shutdown MCP's
        # stdio_client may raise CancelledError as its transport is torn
        # down; that's expected and does NOT affect the in-memory result
        # or the persistence step below. Catch BaseException so the
        # CancelledError doesn't bypass this handler, but re-raise
        # KeyboardInterrupt so Ctrl+C still propagates to the user.
        try:
            await workflow.cleanup()
        except BaseException as cleanup_exc:  # noqa: BLE001
            if isinstance(cleanup_exc, KeyboardInterrupt):
                raise
            logger.warning(
                "workflow.cleanup raised %s — MCP servers may leak; persistence continues",
                type(cleanup_exc).__name__,
            )

        if original_cwd is not None:
            try:
                os.chdir(original_cwd)
            except Exception:
                logger.warning("Could not restore original CWD", exc_info=True)

        # Drop the CLI's registration from server.repository — without this
        # the repo would still report the run as "running" on /api/runs even
        # after the CLI exits, since nothing flips its status. The persisted
        # run record on disk is the authoritative source; the in-memory repo
        # entry was only needed during arun() for _save_incremental.
        try:
            from server.repository import get_repository
            get_repository().remove(run_id)
        except Exception:
            logger.debug("Could not unregister CLI run from repository", exc_info=True)

    # 4) Collect conversation + events + charts from the Bus buffer.
    conv_collector = ConversationCollector(bus)
    conv_collector.collect_from_buffer()
    conversation = conv_collector.get_messages()
    events = list(getattr(bus, "buffer", []))

    chart_collector = ChartCollector(bus)
    chart_groups = chart_collector.get_chart_groups()
    if not chart_groups.get("groupOrder"):
        chart_groups = None  # type: ignore[assignment]

    # 5) Persist. agent_io / todo_steps come from the builder if present.
    agent_io: dict = (
        workflow._builder.agent_io if workflow._builder is not None else {}
    )
    todo_steps: Optional[dict] = None
    if workflow._builder is not None and hasattr(workflow._builder, "todo_states"):
        todo_steps = dict(workflow._builder.todo_states) or None

    result_payload: Optional[dict] = None
    if result is not None:
        result_payload = {
            "outputs": _serialize_outputs(result.outputs),
            "errors": result.errors,
            "trace": [t.model_dump() for t in result.trace],
        }
    elif error is not None:
        result_payload = {"outputs": {}, "errors": {"_workflow": error}, "trace": []}

    bus.emit(
        "workflow.completed" if status == "completed" else "workflow.failed",
        {
            "workflow_id": run_id,
            "outputs": result_payload.get("outputs", {}) if result_payload else {},
            "errors": result_payload.get("errors", {}) if result_payload else {},
        },
    )
    # Re-collect events so the just-emitted completion/error event lands
    # in the persisted record (parity with server which emits THEN saves).
    events = list(getattr(bus, "buffer", []))

    get_run_store().save(
        run_id=run_id,
        workflow_name=workflow.name,
        agents_snapshot=build_agents_snapshot(workflow),
        status=status,
        inputs=inputs,
        result=result_payload,
        dag=build_workflow_dag(workflow),
        agent_io=agent_io,
        conversation=conversation,
        chart_groups=chart_groups,
        events=events,
        work_dir=work_dir,
        todo_steps=todo_steps,
    )

    # Outline sidecar — refresh after the main save so the final on-disk
    # outline reflects every iter that completed. RunStore.save() now uses
    # merge semantics and preserves _has_outline across calls (see
    # run_store.py), so this call only needs to recompute the content with
    # the latest iter_index — no flag gymnastics required.
    try:
        from harness.persistence.outline_save import save_outline_sidecar

        save_outline_sidecar(
            workflow_id=run_id,
            conversation=conversation,
            events=events,
            trace=(result_payload or {}).get("trace", []),
            todo_steps=todo_steps or {},
            agents_snapshot=build_agents_snapshot(workflow),
            dag=build_workflow_dag(workflow),
        )
    except Exception:
        logger.warning(
            "Outline sidecar save failed for CLI run %s — frontend will fall back to deriving",
            run_id,
            exc_info=True,
        )

    # 6) Re-raise on failure AFTER persisting — caller (cmd_run) sets exit code.
    if status == "failed" and error is not None:
        raise RuntimeError(error)

    return run_id, result
