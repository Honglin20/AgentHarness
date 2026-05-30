"""Tests for EventBus."""

import asyncio
import pytest

from harness.extensions.bus import Bus
from server.event_bus import EventBus, get_event_bus


@pytest.fixture
def event_bus():
    """Fresh EventBus for each test."""
    bus = EventBus()
    return bus


@pytest.mark.asyncio
async def test_subscribe_returns_sub_id_and_queue(event_bus):
    """subscribe() returns a sub_id and an asyncio.Queue."""
    sub_id, queue = await event_bus.subscribe()

    assert isinstance(sub_id, str)
    assert isinstance(queue, asyncio.Queue)
    assert event_bus.subscriber_count == 1


@pytest.mark.asyncio
async def test_multiple_subscribers_get_different_ids(event_bus):
    """Each subscriber gets a unique sub_id."""
    sub_id1, _ = await event_bus.subscribe()
    sub_id2, _ = await event_bus.subscribe()

    assert sub_id1 != sub_id2
    assert event_bus.subscriber_count == 2


@pytest.mark.asyncio
async def test_unsubscribe_removes_subscriber(event_bus):
    """unsubscribe() removes the subscriber."""
    sub_id, _ = await event_bus.subscribe()
    assert event_bus.subscriber_count == 1

    await event_bus.unsubscribe(sub_id)
    assert event_bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_is_noop(event_bus):
    """Unsubscribing a non-existent sub_id is a no-op."""
    await event_bus.unsubscribe("nonexistent")
    assert event_bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_emit_delivers_to_all_subscribers(event_bus):
    """emit() delivers events to all subscribers."""
    queue1 = (await event_bus.subscribe())[1]
    queue2 = (await event_bus.subscribe())[1]

    event_bus.emit("test.event", {"foo": "bar"})

    # Both queues should receive the event
    event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)

    assert event1["type"] == "test.event"
    assert event1["payload"] == {"foo": "bar"}
    assert event1 == event2  # Same event content


@pytest.mark.asyncio
async def test_emit_with_no_subscribers_is_noop(event_bus):
    """emit() with no subscribers is a no-op."""
    event_bus.emit("test.event", {"foo": "bar"})
    # Should not raise


@pytest.mark.asyncio
async def test_multiple_events_in_order(event_bus):
    """Events are delivered in the order they were emitted."""
    queue = (await event_bus.subscribe())[1]

    event_bus.emit("test.1", {"seq": 1})
    event_bus.emit("test.2", {"seq": 2})
    event_bus.emit("test.3", {"seq": 3})

    event1 = await queue.get()
    event2 = await queue.get()
    event3 = await queue.get()

    assert event1["payload"]["seq"] == 1
    assert event2["payload"]["seq"] == 2
    assert event3["payload"]["seq"] == 3


@pytest.mark.asyncio
async def test_event_has_timestamp(event_bus):
    """Events include a timestamp."""
    queue = (await event_bus.subscribe())[1]

    event_bus.emit("test", {})

    event = await queue.get()
    assert "ts" in event
    assert isinstance(event["ts"], float)


@pytest.mark.asyncio
async def test_get_event_bus_singleton():
    """get_event_bus() returns the same instance."""
    bus1 = get_event_bus()
    bus2 = get_event_bus()

    assert bus1 is bus2


@pytest.mark.asyncio
async def test_subscribe_unsubscribe_subscribe(event_bus):
    """Can subscribe, unsubscribe, and subscribe again."""
    sub_id1, queue1 = await event_bus.subscribe()
    await event_bus.unsubscribe(sub_id1)

    sub_id2, queue2 = await event_bus.subscribe()

    event_bus.emit("test", {})

    # queue1 should be dead, queue2 should receive
    with pytest.raises((asyncio.TimeoutError, asyncio.InvalidStateError)):
        await asyncio.wait_for(queue1.get(), timeout=0.1)

    event = await asyncio.wait_for(queue2.get(), timeout=1.0)
    assert event["type"] == "test"


@pytest.mark.asyncio
async def test_emit_assigns_monotonic_seq():
    """emit() assigns seq 1, 2, 3... to successive events."""
    bus = Bus()
    bus.emit("test.event", {"a": 1})
    bus.emit("test.event", {"b": 2})
    bus.emit("test.event", {"c": 3})
    buf = bus.buffer
    assert [e["seq"] for e in buf] == [1, 2, 3]


@pytest.mark.asyncio
async def test_subscribe_since_seq():
    """subscribe(since_seq=N) only replays events with seq > N."""
    bus = Bus()
    bus.emit("test.event", {"i": 1})  # seq=1
    bus.emit("test.event", {"i": 2})  # seq=2
    bus.emit("test.event", {"i": 3})  # seq=3

    # Subscribe from seq=2 → should only get event with seq=3
    sub_id, queue = await bus.subscribe(since_seq=2)
    events = []
    while not queue.empty():
        events.append(await queue.get())
    assert len(events) == 1
    assert events[0]["seq"] == 3
    assert events[0]["payload"]["i"] == 3

    await bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_subscribe_since_seq_default_replays_all():
    """subscribe() with no since_seq replays entire buffer (backward compat)."""
    bus = Bus()
    bus.emit("test.event", {"i": 1})
    bus.emit("test.event", {"i": 2})

    sub_id, queue = await bus.subscribe()
    events = []
    while not queue.empty():
        events.append(await queue.get())
    assert len(events) == 2

    await bus.unsubscribe(sub_id)

@pytest.mark.asyncio
async def test_subscribe_since_seq_passes_through_legacy_events_without_seq():
    """Legacy events lacking 'seq' field are always replayed regardless of since_seq.

    Persisted runs created before the seq cursor was introduced have events
    without a 'seq' field. When a rebuilt Bus is reconstructed from such a
    run and the client connects with since_seq=0, those legacy events MUST
    still be delivered — otherwise historical runs appear empty.
    """
    bus = Bus()
    bus._buffer.append({"type": "node.started", "ts": 1.0, "payload": {"i": 1}})  # no seq
    bus._buffer.append({"type": "node.completed", "ts": 2.0, "payload": {"i": 2}})  # no seq

    sub_id, queue = await bus.subscribe(since_seq=0)
    events = []
    while not queue.empty():
        events.append(await queue.get())
    assert len(events) == 2, "legacy events without seq must be replayed"
    assert events[0]["payload"]["i"] == 1
    assert events[1]["payload"]["i"] == 2

    await bus.unsubscribe(sub_id)
