"""Abstract interface for run persistence.

Implementations:
  - RunStore (file-based JSON, default) — harness/run_store.py
  - future: PgRunStore, RedisRunStore, ...

Handlers receive this interface via `Depends(get_run_store_dep)`, so swapping
backends is a one-line change in server/dependencies.py — no handler code
needs to know whether runs live on disk or in a database.

The method signatures mirror the public API of `RunStore` exactly. If
`RunStore` grows a new public method, this interface must declare it too,
otherwise handlers written against the interface will fail at runtime on a
non-file backend.

Sidecar semantics (chart_groups, events stored separately from the main
record) are documented per-method but are NOT part of the contract — a
DB-backed implementation is free to store everything in one row.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class RunStoreInterface(ABC):
    """Persistence layer for workflow run records.

    A run record has:
      - identity:   run_id, workflow_name, user_id, batch_id, created_at
      - definition: agents_snapshot, dag, inputs
      - results:    status, result, agent_io
      - history:    conversation, followup_sessions
      - bulk data:  chart_groups, events (may be stored out-of-line)

    Implementations MAY lazily load chart_groups/events (RunStore does this
    via sidecar files). Callers that need bulk data should use get_charts()
    and get_events() explicitly, NOT assume it is in the main record.
    """

    # ------------------------------------------------------------------ #
    # Write paths
    # ------------------------------------------------------------------ #

    @abstractmethod
    def save(
        self,
        run_id: str,
        workflow_name: str,
        agents_snapshot: list[dict],
        status: str,
        inputs: dict,
        result: dict | None,
        dag: dict | None = None,
        agent_io: dict | None = None,
        batch_id: str | None = None,
        user_id: str | None = None,
        chart_groups: dict | None = None,
        conversation: list[dict] | None = None,
        events: list[dict] | None = None,
        created_at: str | None = None,
        work_dir: str | None = None,
        todo_steps: dict | None = None,
    ) -> Path:
        """Persist a complete run record.

        Implementations SHOULD persist chart_groups and events such that
        get_charts()/get_events() can retrieve them later — either inline
        in the main record or in sidecar storage. Returns the path of the
        main record (file-based impls) or a synthetic path (DB impls).
        """
        ...

    @abstractmethod
    def save_charts(self, run_id: str, chart_groups: dict | None) -> None:
        """Update chart_groups for a previously-saved run."""
        ...

    @abstractmethod
    def save_conversation(self, run_id: str, conversation: list[dict]) -> None:
        """Update the conversation transcript for a previously-saved run."""
        ...

    @abstractmethod
    def update_followup(
        self,
        run_id: str,
        agent_name: str,
        session_data: dict,
    ) -> None:
        """Incrementally update a single agent's follow-up session."""
        ...

    # ------------------------------------------------------------------ #
    # Read paths
    # ------------------------------------------------------------------ #

    @abstractmethod
    def list_runs(
        self,
        workflow_name: str | None = None,
        include_batch: bool = False,
        user_id: str | None = None,
        summary_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        """List runs matching filters, newest first.

        Returns a dict with shape:
            {"runs": [...], "total": int, "has_more": bool}

        - `include_batch=False` (default) excludes batch runs.
        - `user_id=None` means "any user"; passing a user_id filters to that
          user's runs only.
        - `summary_only=True` returns only the lightweight fields needed for
          the run-history sidebar.
        - `limit`/`offset` paginate. If `limit` is None, all matching runs
          are returned and `has_more` is False.
        """
        ...

    @abstractmethod
    def get_run(self, run_id: str) -> dict | None:
        """Load the main record. Does NOT include chart_groups or events.

        Use get_charts() and get_events() to load bulk data lazily.
        Returns None if the run does not exist.
        """
        ...

    @abstractmethod
    def run_exists(self, run_id: str) -> bool:
        """Return True if a run record exists for run_id.

        Cheaper than get_run() when the caller only needs to check presence
        (e.g. delete-path authorization). Implementations MUST NOT expose
        internal storage details (file paths, DB rows) through this method.
        """
        ...

    @abstractmethod
    def get_run_mtime(self, run_id: str) -> float | None:
        """Return the modification time of the run's main record (epoch sec).

        Used by the HTTP layer to populate ``Last-Modified`` and answer
        ``If-Modified-Since`` cheaply. None if the run is absent.
        """
        ...

    @abstractmethod
    def get_charts_mtime(self, run_id: str) -> float | None:
        """Like ``get_run_mtime`` but for the charts sidecar."""
        ...

    @abstractmethod
    def get_events_mtime(self, run_id: str) -> float | None:
        """Like ``get_run_mtime`` but for the events sidecar."""
        ...

    @abstractmethod
    def get_charts(self, run_id: str) -> dict | None:
        """Load chart_groups for a run, or None if absent / not persisted."""
        ...

    @abstractmethod
    def get_events(self, run_id: str) -> list[dict] | None:
        """Load the events buffer for a run, or None if absent / not persisted."""
        ...

    # ------------------------------------------------------------------ #
    # Delete paths
    # ------------------------------------------------------------------ #

    @abstractmethod
    def delete_run(self, run_id: str) -> bool:
        """Delete a run and any associated bulk data. Returns True if deleted."""
        ...

    @abstractmethod
    def delete_followup(self, run_id: str, agent_name: str) -> None:
        """Remove a single agent's follow-up session from the persisted record."""
        ...
