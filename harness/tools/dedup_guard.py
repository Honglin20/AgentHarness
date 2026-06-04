"""Dedup guard for tool calls — prevents identical calls within a short window."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any


class ToolDedupGuard:
    """Tracks recent tool calls and suppresses duplicates within a time window.

    Thread-safe for single-threaded async (no lock needed since Python async
    is cooperative and tool execution is sequential within an agent run).
    """

    def __init__(self, window_ms: int = 5):
        self._window_s = window_ms / 1000.0
        self._seen: dict[str, float] = {}

    def _make_key(self, tool_name: str, kwargs: dict[str, Any]) -> str:
        serialized = json.dumps(kwargs, sort_keys=True, default=str)
        digest = hashlib.md5(serialized.encode()).hexdigest()
        return f"{tool_name}:{digest}"

    def check(self, tool_name: str, kwargs: dict[str, Any]) -> bool:
        """Return True if this is a duplicate call (should skip)."""
        key = self._make_key(tool_name, kwargs)
        now = time.monotonic()

        expired = [k for k, ts in self._seen.items() if now - ts > self._window_s]
        for k in expired:
            del self._seen[k]

        if key in self._seen:
            return True

        self._seen[key] = now
        return False

    def clear(self) -> None:
        self._seen.clear()


_guard: ToolDedupGuard | None = None


def configure_dedup(window_ms: int = 5) -> ToolDedupGuard:
    global _guard
    _guard = ToolDedupGuard(window_ms=window_ms)
    return _guard


def get_dedup_guard() -> ToolDedupGuard | None:
    return _guard
