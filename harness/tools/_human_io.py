"""Shared blocking I/O between agent tools (ask_user) and WS handler.

Holds a process-wide registry of pending question Futures, keyed by question_id.
The WS handler resolves a Future when the user submits an answer.
"""

from __future__ import annotations

import asyncio
from typing import Any

_pending: dict[str, asyncio.Future] = {}
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def register(question_id: str) -> asyncio.Future:
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    lock = _get_lock()
    async with lock:
        _pending[question_id] = future
    return future


async def resolve(question_id: str, answer: Any) -> bool:
    """Set the answer on the pending Future. Returns True if a Future was found."""
    lock = _get_lock()
    async with lock:
        future = _pending.pop(question_id, None)
    if future and not future.done():
        future.set_result(answer)
        return True
    return False


async def wait(future: asyncio.Future, timeout: float) -> Any | None:
    """Wait for a Future with timeout. Returns None on timeout."""
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        return None  # intentional silent fallback — None is the documented timeout sentinel
