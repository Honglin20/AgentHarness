"""In-process event pub/sub for WebSocket broadcasting.

Uses asyncio.Queue per subscriber for non-blocking emit and thread-safe
distribution. EventBus is a singleton at process scope.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import logging

logger = logging.getLogger(__name__)


class EventBus:
    """In-process event broadcaster. Thread-safe, non-blocking emit.

    Usage:
        bus = EventBus()
        # Subscribe (get a queue)
        sub_id, queue = await bus.subscribe()

        # Emit (fire-and-forget into all queues)
        bus.emit("node.started", {"node_id": "analyzer"})

        # Consume events
        while True:
            event = await queue.get()
            print(f"Received: {event}")

        # Unsubscribe
        await bus.unsubscribe(sub_id)
    """

    def __init__(self):
        self._subscribers: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self) -> tuple[str, asyncio.Queue]:
        """Subscribe to events. Returns (sub_id, queue)."""
        async with self._lock:
            sub_id = str(uuid.uuid4())
            queue: asyncio.Queue[dict] = asyncio.Queue()
            self._subscribers[sub_id] = queue
            logger.debug(f"Subscribed: {sub_id}, total: {len(self._subscribers)}")
            return sub_id, queue

    async def unsubscribe(self, sub_id: str) -> None:
        """Unsubscribe from events."""
        async with self._lock:
            if sub_id in self._subscribers:
                del self._subscribers[sub_id]
                logger.debug(f"Unsubscribed: {sub_id}, total: {len(self._subscribers)}")

    def emit(self, event_type: str, payload: dict) -> None:
        """Emit an event to all subscribers. Non-blocking.

        This method is synchronous but put() to asyncio.Queue is safe
        because all subscribers run on the same event loop (the one that
        created the queue via subscribe()).
        """
        event = {
            "type": event_type,
            "ts": asyncio.get_event_loop().time(),
            "payload": payload,
        }

        # Fire-and-forget into all queues
        for sub_id, queue in self._subscribers.items():
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"Queue full for subscriber {sub_id}, event dropped")
            except Exception as e:
                logger.error(f"Error emitting to {sub_id}: {e}")

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._subscribers)


# Singleton instance
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get or create the singleton EventBus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus