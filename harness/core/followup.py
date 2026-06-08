"""Post-workflow follow-up session manager.

Manages multi-turn follow-up conversations between users and agents
after a workflow has completed. Sessions are held in memory for active
use and persisted to RunStore for durability.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Persistence helpers ──────────────────────────────────────────────────


def _serialize_messages(history: list) -> list[dict]:
    """Convert Pydantic AI ModelMessage list to JSON-serializable dicts."""
    result = []
    for msg in history:
        try:
            result.append(msg.model_dump())
        except Exception:
            result.append({"role": "unknown", "content": str(msg)})
    return result


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── Session ──────────────────────────────────────────────────────────────


@dataclass
class FollowUpSession:
    """One (run_id, agent_name) conversation session."""

    agent_name: str
    model: str | None = None
    history: list = field(default_factory=list)  # Pydantic AI ModelMessage list
    turn_count: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Persisted messages from RunStore (used to rebuild context after restart).
    _persisted_messages: list = field(default_factory=list, repr=False)

    def build_context_from_persisted(self) -> str | None:
        """Build a context string from persisted messages for re-injection.

        Called on the first turn after a server restart when the in-memory
        Pydantic AI history is empty but we have persisted JSON messages.
        Returns a formatted string of the previous conversation, or None.
        """
        if not self._persisted_messages:
            return None
        parts = []
        for msg in self._persisted_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"User: {content}")
            elif role in ("assistant", "model"):
                parts.append(f"Assistant: {content}")
            elif content:
                parts.append(f"{role}: {content}")
        return "\n\n".join(parts) if parts else None

    def to_dict(self) -> dict:
        """Serialize session for RunStore persistence."""
        messages = []
        for i, msg in enumerate(self.history):
            try:
                d = msg.model_dump()
                d["_seq"] = i
                messages.append(d)
            except Exception:
                messages.append({"_seq": i, "role": "unknown", "content": str(msg)})

        return {
            "model": self.model,
            "messages": messages,
            "turn_count": self.turn_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ── Manager ──────────────────────────────────────────────────────────────


class FollowUpManager:
    """Process-level singleton managing all follow-up sessions."""

    def __init__(self, max_sessions: int = 500, max_turns: int = 50):
        self._sessions: dict[str, FollowUpSession] = {}
        self._max_sessions = max_sessions
        self._max_turns = max_turns

    def _key(self, run_id: str, agent_name: str) -> str:
        return f"{run_id}::{agent_name}"

    def get_or_create(self, run_id: str, agent_name: str) -> FollowUpSession:
        key = self._key(run_id, agent_name)
        if key not in self._sessions:
            if len(self._sessions) >= self._max_sessions:
                self._evict_oldest()
            self._sessions[key] = FollowUpSession(agent_name=agent_name)
        return self._sessions[key]

    def get(self, run_id: str, agent_name: str) -> FollowUpSession | None:
        return self._sessions.get(self._key(run_id, agent_name))

    def clear(self, run_id: str, agent_name: str) -> None:
        self._sessions.pop(self._key(run_id, agent_name), None)

    def clear_run(self, run_id: str) -> None:
        prefix = f"{run_id}::"
        keys = [k for k in self._sessions if k.startswith(prefix)]
        for k in keys:
            del self._sessions[k]

    def at_turn_limit(self, session: FollowUpSession) -> bool:
        return session.turn_count >= self._max_turns

    # ── Persistence ──────────────────────────────────────────────────────

    def flush_to_store(self, run_id: str) -> None:
        """Write all sessions for a run to RunStore."""
        from harness.run_store import RunStore

        prefix = f"{run_id}::"
        store = RunStore()
        for key, session in self._sessions.items():
            if key.startswith(prefix):
                store.update_followup(run_id, session.agent_name, session.to_dict())

    def flush_session(self, run_id: str, agent_name: str) -> None:
        """Flush a single session to RunStore (called after each turn)."""
        session = self.get(run_id, agent_name)
        if session is None:
            return

        from harness.run_store import RunStore
        store = RunStore()
        store.update_followup(run_id, agent_name, session.to_dict())

    def load_from_store(self, run_id: str) -> None:
        """Restore sessions from RunStore into memory (e.g. on WS connect)."""
        from harness.run_store import RunStore

        store = RunStore()
        record = store.get_run(run_id)
        if not record:
            return

        sessions_data = record.get("followup_sessions")
        if not sessions_data:
            return

        for agent_name, data in sessions_data.items():
            key = self._key(run_id, agent_name)
            if key in self._sessions:
                continue  # Don't overwrite active in-memory session

            session = FollowUpSession(
                agent_name=agent_name,
                model=data.get("model"),
                turn_count=data.get("turn_count", 0),
                created_at=data.get("created_at", _now_iso()),
                updated_at=data.get("updated_at", _now_iso()),
            )
            # We don't restore Pydantic AI ModelMessage objects here —
            # they'll be rebuilt lazily on the first followup turn by
            # re-injecting the serialized messages as context.
            session._persisted_messages = data.get("messages", [])
            self._sessions[key] = session

    def _evict_oldest(self) -> None:
        if self._sessions:
            oldest_key = min(
                self._sessions,
                key=lambda k: self._sessions[k].updated_at,
            )
            del self._sessions[oldest_key]


# ── Singleton ────────────────────────────────────────────────────────────

_manager: FollowUpManager | None = None


def get_followup_manager() -> FollowUpManager:
    global _manager
    if _manager is None:
        _manager = FollowUpManager()
    return _manager
