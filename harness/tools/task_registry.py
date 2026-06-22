"""Per-workflow task registry for long-running background tasks.

In-memory singleton keyed by workflow_id. Tracks TaskRecord lifecycle:
submitted → running → completed | failed | timeout | cancelled.

Coexists with bash.py's _bg_tasks (which tracks Popen objects for
cancel_process). The two are linked: spawn_background accepts an
``on_complete`` callback that lets launch_task update this registry
when the bash monitor observes completion.

Threading: TaskRegistry methods are thread-safe — the bash monitor writes
from a daemon thread, the agent reads from the asyncio loop.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

TaskStatus = Literal[
    "submitted", "running", "completed", "failed", "timeout", "cancelled"
]

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "timeout", "cancelled"}
)


@dataclass
class TaskRecord:
    """A single background task's lifecycle record."""

    task_id: str
    workflow_id: str
    node_id: str
    agent_name: str
    command: str
    description: str
    output_path: str
    pid: int | None
    started_at: float
    completed_at: float | None = None
    exit_code: int | None = None
    status: TaskStatus = "submitted"
    # 0 = never kill (default for MVP — DL training duration is unpredictable).
    # >0 = opt-in safety net; bash monitor will terminate after this many ms.
    timeout_ms: int = 0
    backend: str = "local"
    expected_duration_s: int | None = None
    progress_file: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "agent_name": self.agent_name,
            "command": self.command,
            "description": self.description,
            "output_path": self.output_path,
            "pid": self.pid,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "exit_code": self.exit_code,
            "status": self.status,
            "timeout_ms": self.timeout_ms,
            "backend": self.backend,
            "expected_duration_s": self.expected_duration_s,
            "progress_file": self.progress_file,
        }


class TaskRegistry:
    """Thread-safe in-memory registry of TaskRecords for one workflow."""

    def __init__(self, workflow_id: str = ""):
        self.workflow_id = workflow_id
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.Lock()

    def register(self, task: TaskRecord) -> None:
        with self._lock:
            self._tasks[task.task_id] = task

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **fields) -> TaskRecord | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            for k, v in fields.items():
                if hasattr(task, k):
                    setattr(task, k, v)
            return task

    def list_all(self) -> list[TaskRecord]:
        with self._lock:
            return list(self._tasks.values())

    def list_pending(self) -> list[TaskRecord]:
        with self._lock:
            return [
                t for t in self._tasks.values() if t.status not in TERMINAL_STATUSES
            ]

    def remove(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)


# ──────────────────────────────────────────────────────────────────────
# Module-level singleton keyed by workflow_id (mirrors bash._bg_tasks)
# ──────────────────────────────────────────────────────────────────────

_registries: dict[str, TaskRegistry] = {}
_registries_lock = threading.Lock()


def get_task_registry(workflow_id: str) -> TaskRegistry:
    """Get or create the TaskRegistry for a workflow.

    Empty workflow_id (e.g. tests) maps to a shared "__default__" registry.
    """
    key = workflow_id or "__default__"
    with _registries_lock:
        if key not in _registries:
            _registries[key] = TaskRegistry(workflow_id=key)
        return _registries[key]


def clear_registry(workflow_id: str) -> None:
    """Drop the registry for a workflow. Used by tests."""
    key = workflow_id or "__default__"
    with _registries_lock:
        _registries.pop(key, None)


# ──────────────────────────────────────────────────────────────────────
# Helpers used by launch_task / wait_for_tasks
# ──────────────────────────────────────────────────────────────────────


def emit_task_event(workflow_id: str, event_type: str, payload: dict) -> None:
    """Fire-and-forget task.* event via the workflow's Bus.

    task.submitted/running/completed/failed/timeout/cancelled → critical
    (auto-resolved by bus.CRITICAL_EVENT_TYPES whitelist).
    task.heartbeat → normal.
    """
    if not workflow_id:
        return
    try:
        from server.repository import get_repository

        data = get_repository().get(workflow_id)
        bus = data.get("event_bus") if data else None
        if bus is not None:
            bus.emit(event_type, payload)
    except Exception:
        logger.warning(
            "Failed to emit %s for workflow %s", event_type, workflow_id, exc_info=True
        )


def read_progress(progress_file: str | None) -> dict | None:
    """Read a training script's progress JSON. Returns None on any error."""
    if not progress_file:
        return None
    try:
        return json.loads(Path(progress_file).read_text())
    except Exception:
        return None


def read_output_tail(output_path: str, max_chars: int = 500) -> str:
    """Read the tail of a task's stdout/stderr log."""
    try:
        p = Path(output_path)
        if not p.exists():
            return ""
        content = p.read_text(encoding="utf-8", errors="replace")
        return content[-max_chars:] if len(content) > max_chars else content
    except Exception:
        return ""
