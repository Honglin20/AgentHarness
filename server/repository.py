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


# Singleton
_repo: WorkflowRepository | None = None


def get_repository() -> WorkflowRepository:
    global _repo
    if _repo is None:
        _repo = WorkflowRepository()
    return _repo
