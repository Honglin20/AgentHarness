"""WorkflowRepository — in-memory storage for active workflow runs.

Decouples runner.py from routes.py so neither module imports the other's
module-level state.  Both consume this shared repository instance.
"""

from __future__ import annotations

from typing import Any


class WorkflowRepository:
    """Thread-safe-ish dict for workflow run state + DAG cache.

    Not truly thread-safe (designed for single-process asyncio), but
    all mutations happen inside the event loop so no locking is needed.
    """

    def __init__(self) -> None:
        self._workflows: dict[str, dict[str, Any]] = {}
        self._dag_cache: dict[str, dict] = {}
        self._batches: dict[str, dict[str, Any]] = {}

    # ---- workflow CRUD ----

    def put(self, workflow_id: str, data: dict[str, Any]) -> None:
        self._workflows[workflow_id] = data

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        return self._workflows.get(workflow_id)

    def update_status(
        self,
        workflow_id: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        data = self._workflows.get(workflow_id)
        if data is None:
            return
        data["status"] = status
        if result is not None:
            data["result"] = result

    def remove_event_bus(self, workflow_id: str) -> None:
        """Drop the Bus reference so it can be garbage-collected."""
        data = self._workflows.get(workflow_id)
        if data and "event_bus" in data:
            del data["event_bus"]

    def remove(self, workflow_id: str) -> None:
        """Remove a workflow from the repository."""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
        if workflow_id in self._dag_cache:
            del self._dag_cache[workflow_id]

    def contains(self, workflow_id: str) -> bool:
        return workflow_id in self._workflows

    def all_running(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            (wid, data)
            for wid, data in self._workflows.items()
            if data.get("status") == "running"
        ]

    # ---- DAG cache ----

    def put_dag(self, workflow_id: str, dag: dict) -> None:
        self._dag_cache[workflow_id] = dag

    def get_dag(self, workflow_id: str) -> dict | None:
        return self._dag_cache.get(workflow_id)

    # ---- cleanup (for tests) ----

    def clear(self) -> None:
        self._workflows.clear()
        self._dag_cache.clear()
        self._batches.clear()

    # ---- batch storage ----

    def put_batch(self, batch_id: str, data: dict[str, Any]) -> None:
        self._batches[batch_id] = data

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        return self._batches.get(batch_id)

    def update_batch_run_status(
        self, batch_id: str, workflow_id: str, status: str, **kwargs
    ) -> None:
        """Update a single run's status within a batch."""
        batch = self._batches.get(batch_id)
        if batch is None:
            return
        runs = batch.get("runs", {})
        if workflow_id in runs:
            runs[workflow_id]["status"] = status
            runs[workflow_id].update(kwargs)


# Singleton
_repo: WorkflowRepository | None = None


def get_repository() -> WorkflowRepository:
    global _repo
    if _repo is None:
        _repo = WorkflowRepository()
    return _repo
