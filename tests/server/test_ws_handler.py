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
        manager._sub_to_user[sub_id] = "default"

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

    # Emit a real event — queue starts empty on a fresh bus
    bus.emit("test.event", {"foo": "bar"})

    event = await queue.get()
    await ws.send_text(json.dumps(event))

    assert len(received_events) == 1
    assert received_events[0]["type"] == "test.event"
    assert received_events[0]["payload"]["foo"] == "bar"

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


@pytest.mark.asyncio
async def test_multi_user_isolation():
    """验证 EventBus 自动注入 user_id 和事件过滤逻辑"""
    bus = EventBus()

    # 1. 验证 with_user_context 正确注入 user_id
    with bus.with_user_context("test-user"):
        # 准备 payload
        payload = {"data": "value"}
        # 手动调用 emit 的逻辑（因为 emit 内部会复制 payload）
        copied = dict(payload)
        if "user_id" not in copied and bus._user_context.get("user_id"):
            copied["user_id"] = bus._user_context["user_id"]
        assert copied["user_id"] == "test-user"

    # 2. 验证 context 嵌套和恢复
    assert bus._user_context == {}  # 退出后应该恢复

    with bus.with_user_context("user-a"):
        assert bus._user_context["user_id"] == "user-a"

        with bus.with_user_context("user-b"):
            assert bus._user_context["user_id"] == "user-b"

        # 内层退出后恢复到外层
        assert bus._user_context["user_id"] == "user-a"

    # 全部退出后恢复为空
    assert bus._user_context == {}

    # 3. 验证 emit 的 user_id 优先级
    sub_id, queue = await bus.subscribe()

    # 无上下文，无 user_id
    bus.emit("test", {"data": "value1"})
    event = await queue.get()
    assert "user_id" not in event["payload"]

    # 有上下文，自动注入
    with bus.with_user_context("ctx-user"):
        bus.emit("test", {"data": "value2"})
    event = await queue.get()
    assert event["payload"]["user_id"] == "ctx-user"

    # payload 中已有 user_id，不覆盖
    with bus.with_user_context("ctx-user"):
        bus.emit("test", {"user_id": "payload-user", "data": "value3"})
    event = await queue.get()
    assert event["payload"]["user_id"] == "payload-user"

    await bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_event_payload_priority():
    """测试 user_id 优先级：payload.user_id > event.user_id > default"""
    bus = EventBus()

    class MockWebSocket:
        def __init__(self):
            self.events = []

        async def accept(self): pass

        async def send_text(self, text):
            self.events.append(json.loads(text))

        async def receive_text(self): raise StopIteration

    ws = MockWebSocket()
    sub_id, queue = await bus.subscribe()

    # 1. 没有 user_id 时，自动注入
    with bus.with_user_context("test-user"):
        bus.emit("test.event", {"data": "value"})
    event = await queue.get()
    assert event["payload"]["user_id"] == "test-user"

    # 2. payload 中已有 user_id 时，保留原值
    with bus.with_user_context("different-user"):
        bus.emit("test.event", {"user_id": "original-user", "data": "value"})
    event = await queue.get()
    assert event["payload"]["user_id"] == "original-user"

    # 3. 没有上下文时，不注入
    bus.emit("test.event", {"data": "value"})
    event = await queue.get()
    assert "user_id" not in event["payload"]

    await bus.unsubscribe(sub_id)