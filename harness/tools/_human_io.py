"""Shared blocking I/O between agent tools (ask_user) and WS handler.

Holds a process-wide registry of pending question Futures, keyed by question_id.
The WS handler resolves a Future when the user submits an answer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_pending: dict[str, asyncio.Future] = {}
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _loop_id() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0


async def register(question_id: str) -> asyncio.Future:
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    lock = _get_lock()
    async with lock:
        _pending[question_id] = future
    logger.info(
        "ask_user.register qid=%s future=%s loop=%s pending_size=%d",
        question_id, id(future), id(loop), len(_pending),
    )
    return future


async def resolve(question_id: str, answer: Any) -> bool:
    """Set the answer on the pending Future. Returns True if a Future was found."""
    lock = _get_lock()
    async with lock:
        future = _pending.pop(question_id, None)
    found = future is not None
    already_done = future.done() if future else False
    logger.info(
        "ask_user.resolve qid=%s payload=%r future_found=%s already_done=%s "
        "resolver_loop=%s future_loop=%s match=%s",
        question_id, answer, found, already_done,
        _loop_id(),
        id(future.get_loop()) if future else 0,
        (_loop_id() == id(future.get_loop())) if future else None,
    )
    if future and not future.done():
        future.set_result(answer)
        return True
    return False


async def wait(future: asyncio.Future, timeout: float) -> Any | None:
    """Wait for a Future with timeout. Returns None on timeout."""
    logger.info(
        "ask_user.wait start future=%s timeout=%r awaiter_loop=%s future_loop=%s match=%s",
        id(future), timeout, _loop_id(), id(future.get_loop()),
        _loop_id() == id(future.get_loop()),
    )
    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        logger.info(
            "ask_user.wait resolved future=%s result=%r",
            id(future), result,
        )
        return result
    except asyncio.TimeoutError:
        logger.warning(
            "ask_user.wait TIMEOUT future=%s timeout=%r awaiter_loop=%s",
            id(future), timeout, _loop_id(),
        )
        return None  # intentional silent fallback — None is the documented timeout sentinel
