"""Background workflow execution manager.

Manages concurrent workflow runs with resource limits and cancellation.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from server.event_bus import EventBus

logger = logging.getLogger(__name__)


def _lookup_agent_executor(run_data: dict, node_id: str | None) -> str | None:
    """Look up an agent's executor from agents_snapshot.

    Used by workflow.error payload enrichment to surface which backend
    crashed (e.g. "claude-code" vs "pydantic-ai") so the frontend can
    show executor-specific hints.
    """
    if not node_id:
        return None
    snapshot = run_data.get("agents_snapshot") or []
    for entry in snapshot:
        if isinstance(entry, dict) and entry.get("name") == node_id:
            return entry.get("executor") or "pydantic-ai"
    return None


def _serialize_outputs(outputs: dict) -> dict:
    """Convert BaseModel instances to dicts for JSON serialization."""
    return {
        k: v.model_dump() if isinstance(v, BaseModel) else v
        for k, v in outputs.items()
    }


def _build_agents_snapshot(workflow) -> list[dict]:
    """Build a snapshot of agent definitions with their current MD content."""
    from harness.compiler.md_parser import resolve_agent_md, AgentNotFoundError

    workflow_dir = workflow.workflow_dir
    snapshot = []
    for agent_def in workflow.agents:
        eval_target = getattr(agent_def, "_eval_target", None)
        if eval_target is not None:
            # _judge_X node — synthesize md_content
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
                "---\n"
                "auto_generated: true\n"
                "---\n\n"
                "(passthrough node — no prompt)"
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
        # executor 仅在非默认值时写（与 Agent.to_dict 行为一致），保证旧 snapshot
        # 自动兼容；reconstruct 时 Agent.from_dict 缺省读 DEFAULT_EXECUTOR。
        if getattr(agent_def, "executor", "pydantic-ai") != "pydantic-ai":
            snap["executor"] = agent_def.executor
        if agent_def.result_type is not None:
            from harness.schema_utils import result_type_to_schema

            schema = result_type_to_schema(agent_def.result_type)
            if schema is not None:
                snap["result_type_name"] = agent_def.result_type.__name__
                snap["result_type_schema"] = schema
        snapshot.append(snap)
    return snapshot


class WorkflowRunner:
    """Manages background workflow execution."""

    def __init__(self, max_concurrent: int = 50):
        self.max_concurrent = max_concurrent
        self._running: dict[str, asyncio.Task] = {}
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def submit(
        self,
        workflow_id: str,
        workflow,
        inputs: dict,
        event_bus: EventBus,
        config: dict | None = None,
        resume: bool = False,
        work_dir: str | None = None,
        user_id: str | None = None,
        guidance: str | None = None,
    ) -> None:
        """Submit a workflow to run in the background.

        Args:
            workflow_id: Unique ID for this run
            workflow: The Workflow instance to run
            inputs: Input parameters for the workflow
            event_bus: Event bus for emitting events
            config: LangGraph run config (e.g., checkpoint config for resume)
            resume: Whether resuming from a checkpoint
            work_dir: Working directory to execute in (cd before running)
            user_id: User ID who initiated this run
            guidance: User guidance for interrupt resume (passed to LangGraph Command)
        """
        # Atomic capacity check + task registration under a single lock.
        #
        # Previously the capacity check lived only in the route handlers,
        # which created a TOCTOU race: two concurrent requests could both
        # read `running_count < max_concurrent`, both pass, and both
        # register — over-subscribing the runner. The check-in-route is
        # now defense in depth; the authoritative gate lives here, in the
        # same lock scope as the `_running` mutation, so the check and the
        # registration cannot be interleaved by another coroutine.
        async with self._lock:
            if workflow_id in self._running:
                raise RuntimeError(f"Workflow {workflow_id} is already running")

            if len(self._running) >= self.max_concurrent:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Max {self.max_concurrent} concurrent workflows. "
                        "Wait for one to finish."
                    ),
                )

            if workflow_id in self._cancelled:
                self._cancelled.remove(workflow_id)

            # Create the background task while still holding the lock so the
            # capacity count is authoritative by the time we release it.
            # `asyncio.create_task` only *schedules* the coroutine — it does
            # not start running synchronously, so `_run_workflow`'s own
            # `async with self._semaphore` (and any lock acquisitions) cannot
            # deadlock against us here.
            task = asyncio.create_task(
                self._run_workflow(
                    workflow_id=workflow_id,
                    workflow=workflow,
                    inputs=inputs,
                    event_bus=event_bus,
                    config=config,
                    resume=resume,
                    work_dir=work_dir,
                    user_id=user_id,
                    guidance=guidance,
                )
            )
            self._running[workflow_id] = task

    async def cancel(self, workflow_id: str) -> bool:
        """Pause a running workflow (sets status to 'paused')."""
        async with self._lock:
            if workflow_id not in self._running:
                return False

            self._cancelled.add(workflow_id)
            task = self._running[workflow_id]
            task.cancel()

            # Wait a bit for graceful cancellation
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

            # Clean up runner state (keep entry for resume)
            del self._running[workflow_id]
            if workflow_id in self._cancelled:
                self._cancelled.remove(workflow_id)

            # Clear any stale stop-and-regenerate signals so they don't
            # fire on the next run after resume.
            try:
                from harness.engine.macro_graph import clear_stop_regen
                clear_stop_regen(workflow_id)
            except Exception:
                logger.warning(
                    "Failed to clear stop_regen signal for %s", workflow_id, exc_info=True,
                )

            # Persist as paused so the run stays in history and can be resumed
            # Merge with existing disk record to preserve agent_io/conversation/events
            # (written by _save_incremental after each node completion)
            from server.repository import get_repository
            repo = get_repository()
            data = repo.get(workflow_id)

            if data is not None:
                workflow = data["workflow"]
                data["status"] = "paused"
                batch_id = data.get("batch_id")
                from harness.run_store import get_run_store
                store = get_run_store()
                existing = store.get_run(workflow_id) or {}
                try:
                    store.save(
                        run_id=workflow_id,
                        workflow_name=workflow.name,
                        agents_snapshot=data.get("agents_snapshot")
                            or _build_agents_snapshot(workflow),
                        status="paused",
                        inputs=data.get("inputs", {}),
                        result=existing.get("result"),
                        dag=repo.get_dag(workflow_id),
                        agent_io=existing.get("agent_io"),
                        batch_id=batch_id or existing.get("batch_id"),
                        user_id=data.get("user_id") or existing.get("user_id"),
                        conversation=existing.get("conversation"),
                        chart_groups=store.get_charts(workflow_id),
                        events=store.get_events(workflow_id),
                        created_at=existing.get("created_at"),
                        work_dir=data.get("work_dir") or existing.get("work_dir"),
                    )
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Failed to persist paused run %s", workflow_id)

            return True

    async def _run_workflow(
        self,
        workflow_id: str,
        workflow,
        inputs: dict,
        event_bus: EventBus,
        config: dict | None = None,
        resume: bool = False,
        work_dir: str | None = None,
        user_id: str | None = None,
        guidance: str | None = None,
    ) -> None:
        """Internal: execute workflow with cancellation check.

        Args:
            workflow_id: Unique ID for this run
            workflow: The Workflow instance to run
            inputs: Input parameters for the workflow
            event_bus: Event bus for emitting events
            config: LangGraph run config (e.g., checkpoint config for resume)
            resume: Whether resuming from a checkpoint
            work_dir: Working directory to execute in (cd before running)
            user_id: User ID who initiated this run
            guidance: User guidance for interrupt resume (passed to LangGraph Command)
        """
        import os
        original_cwd = None

        async with self._semaphore:
            try:
                # Check cancellation before starting
                if await self._is_cancelled(workflow_id):
                    event_bus.emit("workflow.cancelled", {"workflow_id": workflow_id, "user_id": user_id})
                    return

                # Change to working directory if specified
                if work_dir:
                    # Resolve to absolute path and validate bounds
                    work_path = Path(work_dir).resolve()
                    # "/" means full filesystem access — skip all checks
                    if str(work_path) != "/":
                        forbidden_prefixes = ["/etc", "/proc", "/sys", "/root", "/var"]
                        for prefix in forbidden_prefixes:
                            if str(work_path).startswith(prefix):
                                raise RuntimeError(f"Work directory cannot be under {prefix}")

                    if not work_path.exists():
                        raise RuntimeError(f"Work directory does not exist: {work_dir}")
                    if not work_path.is_dir():
                        raise RuntimeError(f"Work path is not a directory: {work_dir}")

                    original_cwd = os.getcwd()
                    os.chdir(work_path)

                # Connect MCP servers and register their tools
                await workflow.setup(work_dir=work_dir)

                # Set workflow_id on builder for interrupt support
                if workflow._builder is not None:
                    workflow._builder.workflow_id = workflow_id
                    workflow._builder.register_active()

                # Run workflow (resume from checkpoint or fresh start)
                # 使用用户上下文，确保事件携带 user_id
                from contextlib import nullcontext
                ctx = event_bus.with_user_context(user_id) if user_id else nullcontext()
                with ctx:
                    if resume and config:
                        result = await workflow.arun(
                            inputs=None, config=config,
                            resume_value=guidance,
                        )
                    else:
                        result = await workflow.arun(inputs, config=config)

                # Store result for REST endpoints
                from server.repository import get_repository
                repo = get_repository()
                if repo.contains(workflow_id):
                    repo.update_status(workflow_id, "completed", {
                        "outputs": _serialize_outputs(result.outputs),
                        "errors": result.errors,
                        "trace": [t.model_dump() for t in result.trace],
                    })

                    # Update batch status if this run belongs to a batch
                    wf_data = repo.get(workflow_id)
                    batch_id = wf_data.get("batch_id") if wf_data else None
                    if batch_id:
                        repo.update_batch_run_status(batch_id, workflow_id, "completed")

                # Emit completion BEFORE persisting so the event lands in the
                # buffer and gets saved with the run — replay needs it to
                # trigger computeRunSummary on the frontend.
                completion_payload = {
                    "workflow_id": workflow_id,
                    "user_id": user_id,
                    "outputs": _serialize_outputs(result.outputs),
                    "errors": result.errors,
                    "trace": [t.model_dump() for t in result.trace],
                }
                if batch_id:
                    completion_payload["batch_id"] = batch_id
                event_bus.emit("workflow.completed", completion_payload)

                # Persist run to disk (with event-ordered conversation + charts)
                from harness.run_store import get_run_store
                from harness.extensions.collectors import ConversationCollector, ChartCollector
                _agent_io = workflow._builder.agent_io if workflow._builder else {}
                _todo_steps = dict(workflow._builder.todo_states) if workflow._builder else {}
                data = repo.get(workflow_id)

                if event_bus:
                    conv_collector = ConversationCollector(event_bus)
                    conv_collector.collect_from_buffer()
                    conversation = conv_collector.get_messages()
                    events = list(event_bus.buffer)

                    chart_collector = ChartCollector(event_bus)
                    chart_groups = chart_collector.get_chart_groups()
                    if not chart_groups.get("groupOrder"):
                        chart_groups = None
                else:
                    from harness.extensions.collectors import build_conversation as _build_conv
                    conversation = _build_conv(_agent_io)
                    events = []
                    chart_groups = None

                get_run_store().save(
                    run_id=workflow_id,
                    workflow_name=workflow.name,
                    agents_snapshot=data.get("agents_snapshot")
                        or _build_agents_snapshot(workflow) if data else _build_agents_snapshot(workflow),
                    status="completed",
                    inputs=inputs,
                    result=data.get("result") if data else None,
                    dag=repo.get_dag(workflow_id),
                    agent_io=_agent_io,
                    batch_id=batch_id,
                    user_id=user_id,
                    conversation=conversation,
                    chart_groups=chart_groups,
                    events=events,
                    created_at=data.get("created_at") if data else None,
                    work_dir=work_dir,
                    todo_steps=_todo_steps or None,
                )

                # Write outline sidecar — pre-computed per-(nodeId, iter) summary
                # so the frontend can render the outline without scanning the full
                # conversation (replay mode).
                from harness.persistence.outline_save import save_outline_sidecar

                save_outline_sidecar(
                    workflow_id=workflow_id,
                    conversation=conversation,
                    events=events,
                    trace=(data.get("result") or {}).get("trace", []) if data else [],
                    todo_steps=_todo_steps,
                    agents_snapshot=data.get("agents_snapshot")
                        or _build_agents_snapshot(workflow) if data else _build_agents_snapshot(workflow),
                    dag=repo.get_dag(workflow_id),
                )

            except Exception as e:
                # Store error for REST endpoints
                from server.repository import get_repository
                repo = get_repository()
                if repo.contains(workflow_id):
                    repo.update_status(workflow_id, "failed", {
                        "outputs": {},
                        "errors": {"_workflow": str(e)},
                        "trace": [],
                    })

                    # Update batch status if this run belongs to a batch
                    wf_data = repo.get(workflow_id)
                    batch_id = wf_data.get("batch_id") if wf_data else None
                    if batch_id:
                        repo.update_batch_run_status(
                            batch_id, workflow_id, "failed", error=str(e)
                        )

                # P2-T6: workflow.error payload enriched with executor-side
                # context so sinks (frontend / CLI / replay) can render the
                # failure cause without scraping other events. When e is an
                # ExecutorError, propagate stderr_tail / phase / executor /
                # exit_code / executor_extra from the embedded ErrorEvent.
                error_payload = {
                    "workflow_id": workflow_id,
                    "user_id": user_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                }

                # ExecutorError carries a structured ErrorEvent — extract
                # its fields onto the payload top-level (matches the
                # agent.executor_event shape for sink-side uniformity).
                from harness.engine.error_event import ExecutorError
                if isinstance(e, ExecutorError):
                    ev = e.error_event
                    error_payload["executor"] = ev.executor
                    if ev.phase:
                        error_payload["phase"] = ev.phase
                    if ev.stderr_tail:
                        error_payload["stderr_tail"] = ev.stderr_tail
                    if ev.exit_code is not None:
                        error_payload["exit_code"] = ev.exit_code
                    if ev.extra:
                        error_payload["executor_extra"] = dict(ev.extra)

                # failed_node: reverse-scan the bus buffer for the most
                # recent node.failed event so the frontend can highlight
                # which agent crashed (workflow-level errors don't always
                # carry this; ExecutorError.node_id is the same info but
                # only present on ExecutorError path).
                if "failed_node" not in error_payload:
                    for evt_type, evt_payload in reversed(getattr(event_bus, "buffer", [])):
                        if evt_type == "node.failed":
                            error_payload["failed_node"] = evt_payload.get("node_id")
                            # Also surface executor from agents_snapshot if not
                            # already set (covers non-ExecutorError paths).
                            if "executor" not in error_payload:
                                snap = _lookup_agent_executor(
                                    repo.get(workflow_id) or {},
                                    evt_payload.get("node_id"),
                                )
                                if snap:
                                    error_payload["executor"] = snap
                            break

                if batch_id:
                    error_payload["batch_id"] = batch_id
                event_bus.emit("workflow.error", error_payload)

                # Persist failed run to disk (with event-ordered conversation)
                from harness.run_store import get_run_store
                from harness.extensions.collectors import ConversationCollector, ChartCollector
                _agent_io = workflow._builder.agent_io if workflow._builder else {}
                _todo_steps = dict(workflow._builder.todo_states) if workflow._builder else {}
                data = repo.get(workflow_id)

                if event_bus:
                    conv_collector = ConversationCollector(event_bus)
                    conv_collector.collect_from_buffer()
                    conversation = conv_collector.get_messages()
                    events = list(event_bus.buffer)

                    chart_collector = ChartCollector(event_bus)
                    chart_groups = chart_collector.get_chart_groups()
                    if not chart_groups.get("groupOrder"):
                        chart_groups = None
                else:
                    from harness.extensions.collectors import build_conversation as _build_conv
                    conversation = _build_conv(_agent_io)
                    events = []
                    chart_groups = None

                get_run_store().save(
                    run_id=workflow_id,
                    workflow_name=workflow.name,
                    agents_snapshot=data.get("agents_snapshot")
                        or _build_agents_snapshot(workflow) if data else _build_agents_snapshot(workflow),
                    status="failed",
                    inputs=inputs,
                    result=None,
                    dag=repo.get_dag(workflow_id),
                    agent_io=_agent_io,
                    batch_id=batch_id,
                    user_id=user_id,
                    conversation=conversation,
                    chart_groups=chart_groups,
                    events=events,
                    created_at=data.get("created_at") if data else None,
                    work_dir=work_dir,
                    todo_steps=_todo_steps or None,
                )

                # Outline sidecar for failed runs too — frontend outline should
                # reflect which nodes succeeded before the failure.
                from harness.persistence.outline_save import save_outline_sidecar

                save_outline_sidecar(
                    workflow_id=workflow_id,
                    conversation=conversation,
                    events=events,
                    trace=[],
                    todo_steps=_todo_steps,
                    agents_snapshot=data.get("agents_snapshot")
                        or _build_agents_snapshot(workflow) if data else _build_agents_snapshot(workflow),
                    dag=repo.get_dag(workflow_id),
                )

            finally:
                # Restore working directory
                if original_cwd:
                    os.chdir(original_cwd)

                # Disconnect MCP servers
                await workflow.cleanup()
                # Unregister builder from global signal map
                if workflow._builder is not None:
                    workflow._builder.unregister_active()
                # Release Bus reference so it can be garbage-collected
                from server.repository import get_repository
                get_repository().remove_event_bus(workflow_id)
                # Clean up
                async with self._lock:
                    if workflow_id in self._running:
                        del self._running[workflow_id]
                    if workflow_id in self._cancelled:
                        self._cancelled.remove(workflow_id)

    async def _is_cancelled(self, workflow_id: str) -> bool:
        """Check if workflow is cancelled."""
        async with self._lock:
            return workflow_id in self._cancelled

    def _cleanup_stale_tasks(self) -> None:
        """Remove completed/cancelled tasks from _running dict.

        This is called automatically before running_count to ensure accurate counts.
        """
        stale_ids = []
        for workflow_id, task in self._running.items():
            if task.done() or task.cancelled():
                stale_ids.append(workflow_id)

        for workflow_id in stale_ids:
            self._running.pop(workflow_id, None)

    @property
    def running_count(self) -> int:
        """Number of currently running workflows."""
        self._cleanup_stale_tasks()
        return len(self._running)

    @property
    def running_ids(self) -> list[str]:
        """IDs of currently running workflows."""
        self._cleanup_stale_tasks()
        return list(self._running.keys())


# Singleton instance
_runner: WorkflowRunner | None = None


def get_runner() -> WorkflowRunner:
    """Get or create the singleton WorkflowRunner instance."""
    global _runner
    if _runner is None:
        _runner = WorkflowRunner()
    return _runner
