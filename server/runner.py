"""Background workflow execution manager.

Manages concurrent workflow runs with resource limits and cancellation.
"""

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from server.event_bus import EventBus


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
                pass

        snapshot.append({
            "name": agent_def.name,
            "after": agent_def.after,
            "md_content": md_content,
            "tools": agent_def.tools,
            "model": agent_def.model,
            "retries": agent_def.retries,
        })
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
        """
        async with self._lock:
            if workflow_id in self._running:
                raise RuntimeError(f"Workflow {workflow_id} is already running")

            if workflow_id in self._cancelled:
                self._cancelled.remove(workflow_id)

        # Create background task
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
            )
        )

        async with self._lock:
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
                pass

            # Persist as paused so the run stays in history and can be resumed
            from server.repository import get_repository
            repo = get_repository()
            data = repo.get(workflow_id)
            if data is not None:
                workflow = data["workflow"]
                data["status"] = "paused"
                batch_id = data.get("batch_id")
                from harness.run_store import RunStore
                try:
                    RunStore().save(
                        run_id=workflow_id,
                        workflow_name=workflow.name,
                        agents_snapshot=data.get("agents_snapshot")
                            or _build_agents_snapshot(workflow),
                        status="paused",
                        inputs=data.get("inputs", {}),
                        result=None,
                        dag=repo.get_dag(workflow_id),
                        batch_id=batch_id,
                    )
                except Exception:
                    pass

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
        """
        import os
        original_cwd = None

        async with self._semaphore:
            try:
                # Check cancellation before starting
                if await self._is_cancelled(workflow_id):
                    event_bus.emit("workflow.cancelled", {"workflow_id": workflow_id})
                    return

                # Change to working directory if specified
                if work_dir:
                    # Resolve to absolute path and validate bounds
                    work_path = Path(work_dir).resolve()
                    # Restrict to reasonable paths (prevent /etc/, /proc/, etc.)
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
                await workflow.setup()

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
                        result = await workflow.arun(inputs=None, config=config)
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

                # Persist run to disk (with event-ordered conversation + charts)
                from harness.run_store import RunStore
                from harness.extensions.collectors import ConversationCollector, ChartCollector
                _agent_io = workflow._builder.agent_io if workflow._builder else {}
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

                RunStore().save(
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
                )

                # Emit completion
                completion_payload = {
                    "workflow_id": workflow_id,
                    "outputs": _serialize_outputs(result.outputs),
                    "errors": result.errors,
                    "trace": [t.model_dump() for t in result.trace],
                }
                if batch_id:
                    completion_payload["batch_id"] = batch_id
                event_bus.emit("workflow.completed", completion_payload)

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

                # Persist failed run to disk (with event-ordered conversation)
                from harness.run_store import RunStore
                from harness.extensions.collectors import ConversationCollector, ChartCollector
                _agent_io = workflow._builder.agent_io if workflow._builder else {}
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

                RunStore().save(
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
                )

                error_payload = {
                    "workflow_id": workflow_id,
                    "error": str(e),
                }
                if batch_id:
                    error_payload["batch_id"] = batch_id
                event_bus.emit("workflow.error", error_payload)

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
