"""Checkpoint management — SQLite-backed LangGraph checkpointer lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


from harness.paths import get_checkpoint_db_path

_DEFAULT_DB_PATH = get_checkpoint_db_path()


class CheckpointManager:
    """Manages a single SQLite-backed checkpointer for all workflow runs.

    Usage:
        mgr = get_checkpoint_manager()
        checkpointer = await mgr.get_checkpointer()
        # ... pass checkpointer to Workflow / graph.compile() ...
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._checkpointer: AsyncSqliteSaver | None = None
        self._cm: Any = None  # context manager from from_conn_string

    async def get_checkpointer(self) -> AsyncSqliteSaver:
        """Get or create the singleton AsyncSqliteSaver."""
        if self._checkpointer is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._cm = AsyncSqliteSaver.from_conn_string(str(self.db_path))
            self._checkpointer = await self._cm.__aenter__()
            await self._checkpointer.setup()
        return self._checkpointer

    async def list_checkpoints(self, compiled_graph, thread_id: str) -> list[dict[str, Any]]:
        """List all checkpoints for a workflow run (thread_id = workflow_id).

        Args:
            compiled_graph: The compiled LangGraph (has aget_state_history).
            thread_id: The thread_id used during ainvoke.

        Returns list ordered newest-first. Each entry contains:
            checkpoint_id, next_nodes, values
        """
        config = {"configurable": {"thread_id": thread_id}}

        checkpoints = []
        async for state in compiled_graph.aget_state_history(config):
            checkpoints.append({
                "checkpoint_id": state.config["configurable"].get("checkpoint_id", ""),
                "thread_id": thread_id,
                "next_nodes": list(state.next) if state.next else [],
                "values": state.values if state.values is not None else {},
            })

        return checkpoints

    async def get_checkpoint_config(self, compiled_graph, thread_id: str, checkpoint_id: str) -> dict | None:
        """Get the config for a specific checkpoint (for resume)."""
        checkpoints = await self.list_checkpoints(compiled_graph, thread_id)
        for cp in checkpoints:
            if cp["checkpoint_id"] == checkpoint_id:
                return {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": checkpoint_id,
                    },
                }
        return None

    async def get_latest_checkpoint_config(self, compiled_graph, thread_id: str) -> dict | None:
        """Get config for the most recent non-final checkpoint (for resume).

        Skips the final state (next_nodes empty) — resume from the last
        state that still has work to do.
        """
        checkpoints = await self.list_checkpoints(compiled_graph, thread_id)
        for cp in checkpoints:
            if cp["next_nodes"]:
                return {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": cp["checkpoint_id"],
                    },
                }
        return None

    async def close(self) -> None:
        """Close the database connection."""
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._checkpointer = None
            self._cm = None


# Singleton
_manager: CheckpointManager | None = None


def get_checkpoint_manager() -> CheckpointManager:
    """Get or create the singleton CheckpointManager."""
    global _manager
    if _manager is None:
        _manager = CheckpointManager()
    return _manager
