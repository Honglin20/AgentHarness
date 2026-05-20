"""Background workflow execution manager.

Manages concurrent workflow runs with resource limits and cancellation.
"""

import asyncio
from typing import Any

from server.event_bus import EventBus


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
                # Emit start event
                event_bus.emit("workflow.started", {
                    "workflow_id": workflow_id,
                    "name": workflow.name,
                    "inputs": inputs,
                })

                # Check cancellation before starting
                if await self._is_cancelled(workflow_id):
                    event_bus.emit("workflow.cancelled", {"workflow_id": workflow_id})
                    return

                # Run workflow
                result = await workflow.arun(inputs)

                # Emit completion
                event_bus.emit("workflow.completed", {
                    "workflow_id": workflow_id,
                    "outputs": result.outputs,
                    "errors": result.errors,
                    "trace": [t.model_dump() for t in result.trace],
                })

            except Exception as e:
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