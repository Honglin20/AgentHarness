"""Background workflow execution manager.

Manages concurrent workflow runs with resource limits and cancellation.
"""

import asyncio
from pathlib import Path
from typing import Any

from server.event_bus import EventBus


def _build_agents_snapshot(workflow) -> list[dict]:
    """Build a snapshot of agent definitions with their current MD content."""
    from harness.compiler.md_parser import resolve_agent_md, AgentNotFoundError

    workflow_dir = workflow.workflow_dir
    snapshot = []
    for agent_def in workflow.agents:
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

    def __init__(self, max_concurrent: int = 4):
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
    ) -> None:
        """Submit a workflow to run in the background."""
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
            )
        )

        async with self._lock:
            self._running[workflow_id] = task

    async def cancel(self, workflow_id: str) -> bool:
        """Cancel a running workflow."""
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

            # Clean up
            del self._running[workflow_id]
            if workflow_id in self._cancelled:
                self._cancelled.remove(workflow_id)

            # Persist a cancelled record so the run shows up in history
            from server.routes import _workflows, _dag_cache
            data = _workflows.get(workflow_id)
            if data is not None:
                workflow = data["workflow"]
                from harness.run_store import RunStore
                try:
                    RunStore().save(
                        run_id=workflow_id,
                        workflow_name=workflow.name,
                        agents_snapshot=data.get("agents_snapshot")
                            or _build_agents_snapshot(workflow),
                        status="cancelled",
                        inputs=data.get("inputs", {}),
                        result=None,
                        dag=_dag_cache.get(workflow_id),
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
    ) -> None:
        """Internal: execute workflow with cancellation check."""
        async with self._semaphore:
            try:
                # workflow.started is already emitted by routes.py with the DAG.
                # Do NOT emit a second one here — it would lack the DAG data
                # and cause duplicate processing on the frontend.

                # Check cancellation before starting
                if await self._is_cancelled(workflow_id):
                    event_bus.emit("workflow.cancelled", {"workflow_id": workflow_id})
                    return

                # Set workflow_id on builder for interrupt support
                if workflow._builder is not None:
                    workflow._builder.workflow_id = workflow_id

                # Run workflow
                result = await workflow.arun(inputs)

                # Store result for REST endpoints
                from server.routes import _workflows
                if workflow_id in _workflows:
                    _workflows[workflow_id]["status"] = "completed"
                    _workflows[workflow_id]["result"] = {
                        "outputs": result.outputs,
                        "errors": result.errors,
                        "trace": [t.model_dump() for t in result.trace],
                    }

                # Persist run to disk
                from harness.run_store import RunStore
                from server.routes import _dag_cache
                RunStore().save(
                    run_id=workflow_id,
                    workflow_name=workflow.name,
                    agents_snapshot=_workflows[workflow_id].get("agents_snapshot")
                        or _build_agents_snapshot(workflow),
                    status="completed",
                    inputs=inputs,
                    result=_workflows[workflow_id]["result"],
                    dag=_dag_cache.get(workflow_id),
                )

                # Emit completion
                event_bus.emit("workflow.completed", {
                    "workflow_id": workflow_id,
                    "outputs": result.outputs,
                    "errors": result.errors,
                    "trace": [t.model_dump() for t in result.trace],
                })

            except Exception as e:
                # Store error for REST endpoints
                from server.routes import _workflows
                if workflow_id in _workflows:
                    _workflows[workflow_id]["status"] = "failed"
                    _workflows[workflow_id]["result"] = {
                        "outputs": {},
                        "errors": {"_workflow": str(e)},
                        "trace": [],
                    }

                # Persist failed run to disk
                from harness.run_store import RunStore
                from server.routes import _dag_cache
                RunStore().save(
                    run_id=workflow_id,
                    workflow_name=workflow.name,
                    agents_snapshot=_workflows[workflow_id].get("agents_snapshot")
                        or _build_agents_snapshot(workflow),
                    status="failed",
                    inputs=inputs,
                    result=None,
                    dag=_dag_cache.get(workflow_id),
                )

                event_bus.emit("workflow.error", {
                    "workflow_id": workflow_id,
                    "error": str(e),
                })

            finally:
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

    @property
    def running_count(self) -> int:
        """Number of currently running workflows."""
        return len(self._running)


# Singleton instance
_runner: WorkflowRunner | None = None


def get_runner() -> WorkflowRunner:
    """Get or create the singleton WorkflowRunner instance."""
    global _runner
    if _runner is None:
        _runner = WorkflowRunner()
    return _runner
