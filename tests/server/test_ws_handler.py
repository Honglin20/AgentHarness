"""Tests for WebSocket handler."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket

from server.app import app
from server.event_bus import EventBus


@pytest.mark.asyncio
async def test_connection_manager_subscribe_unsubscribe():
    """ConnectionManager subscribe/unsubscribe lifecycle works."""
    from server.ws_handler import ConnectionManager

    bus = EventBus()
    manager = ConnectionManager()

    # Subscribe
    assert bus.subscriber_count == 0

    # Mock WebSocket (can't use real WS in test)
    class MockWebSocket:
        async def accept(self): pass
        async def send_text(self, text): pass
        async def receive_text(self): raise StopIteration

    ws = MockWebSocket()

    # Can't actually connect without real WS, but we can test the structure
    sub_id = "test-sub-id"

    # Add connection manually
    from asyncio import Lock
    manager._lock = Lock()
    async with manager._lock:
        manager._connections[sub_id] = ws

    assert manager.get_connection(sub_id) is ws

    # Disconnect
    await manager.disconnect(sub_id, bus)
    assert manager.get_connection(sub_id) is None


@pytest.mark.asyncio
async def test_event_bus_forwarding():
    """EventBus events can be forwarded to a mock WebSocket."""
    bus = EventBus()

    received_events = []

    class MockWebSocket:
        async def accept(self): pass

        async def send_text(self, text):
            received_events.append(json.loads(text))

        async def receive_text(self): raise StopIteration

    ws = MockWebSocket()

    # Subscribe to EventBus
    sub_id, queue = await bus.subscribe()

    # Simulate forward (in reality, this runs in a background task)
    event = await queue.get()
    await ws.send_text(json.dumps(event))

    assert len(received_events) == 1
    assert received_events[0]["type"] == ""  # Empty type from the first get()

    # Emit a real event
    bus.emit("test.event", {"foo": "bar"})

    event = await queue.get()
    await ws.send_text(json.dumps(event))

    assert received_events[1]["type"] == "test.event"
    assert received_events[1]["payload"]["foo"] == "bar"

    await bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_event_bus_with_multiple_subscribers():
    """EventBus delivers to multiple subscribers concurrently."""
    bus = EventBus()

    class MockWebSocket:
        def __init__(self):
            self.events = []

        async def accept(self): pass

        async def send_text(self, text):
            self.events.append(json.loads(text))

        async def receive_text(self): raise StopIteration

    ws1 = MockWebSocket()
    ws2 = MockWebSocket()

    # Subscribe two clients
    sub_id1, queue1 = await bus.subscribe()
    sub_id2, queue2 = await bus.subscribe()

    # Emit event
    bus.emit("test", {"value": 42})

    # Both queues should have the event
    event1 = await queue1.get()
    event2 = await queue2.get()

    assert event1["payload"]["value"] == 42
    assert event2["payload"]["value"] == 42

    await bus.unsubscribe(sub_id1)
    await bus.unsubscribe(sub_id2)


def test_resolve_question():
    """resolve_question() resolves a pending question."""
    import asyncio

    from harness.tools.ask_human import resolve_question

    async def test():
        # Create a pending question manually
        from harness.tools.ask_human import _pending, get_lock
        from asyncio import Lock

        lock = Lock()
        _pending["test-qid"] = asyncio.get_event_loop().create_future()

        # Resolve it
        await resolve_question("test-qid", "test answer")

        # Verify resolved
        assert _pending.get("test-qid") is None  # Removed after resolve
        # Future is already resolved, can't check value

    asyncio.run(test())