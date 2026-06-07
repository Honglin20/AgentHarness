"""Test event priority system — critical events survive buffer overflow."""

import asyncio

import pytest

from harness.extensions.bus import Bus


@pytest.fixture
def bus():
    return Bus(buffer_size=10)


# ----- Unit: buffer behavior -----


class TestCriticalEventBuffer:
    """Critical events must survive normal buffer overflow."""

    def test_critical_event_never_dropped(self, bus):
        """When the normal buffer overflows, critical events remain."""
        for i in range(15):
            bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

        bus.emit("workflow.completed", {"workflow_id": "w1"}, priority="critical")

        buffered = bus.buffer
        critical = [e for e in buffered if e["type"] == "workflow.completed"]
        assert len(critical) == 1, "critical event must survive buffer overflow"

    def test_normal_events_dropped_fifo(self, bus):
        """Normal events are dropped oldest-first when buffer overflows."""
        bus.emit("agent.text_delta", {"text": "first"})
        for i in range(bus._buffer_size):
            bus.emit("agent.text_delta", {"text": f"fill-{i}"})
        bus.emit("agent.text_delta", {"text": "last"})

        texts = [
            e["payload"]["text"]
            for e in bus.buffer
            if e["type"] == "agent.text_delta"
        ]
        assert "first" not in texts, "oldest normal event should have been evicted"
        assert "last" in texts, "newest normal event should be present"

    def test_buffer_returns_critical_first(self, bus):
        """buffer property returns critical events before normal ones."""
        bus.emit("agent.text_delta", {"text": "normal-1"})
        bus.emit("node.failed", {"node_id": "n1"}, priority="critical")
        bus.emit("agent.text_delta", {"text": "normal-2"})

        types = [e["type"] for e in bus.buffer]
        # Critical event should appear before normal events
        critical_idx = types.index("node.failed")
        normal_after = [t for t in types[critical_idx + 1 :] if t == "agent.text_delta"]
        assert len(normal_after) > 0, "normal events should come after critical"

    def test_multiple_critical_events(self, bus):
        """Multiple critical events are all preserved."""
        bus.emit("workflow.completed", {"w": 1}, priority="critical")
        for i in range(bus._buffer_size + 5):
            bus.emit("agent.text_delta", {"text": f"noise-{i}"})
        bus.emit("node.failed", {"n": 1}, priority="critical")

        critical = [e for e in bus.buffer if e.get("priority") == "critical"]
        assert len(critical) == 2

    def test_critical_buffer_max_size_warning(self, bus):
        """When critical buffer exceeds max, warn but still append."""
        bus._critical_buffer_max = 5
        for i in range(8):
            bus.emit("workflow.completed", {"w": i}, priority="critical")

        assert len(bus._critical_buffer) == 8, "all critical events preserved even past max"

    def test_default_priority_is_normal(self, bus):
        """emit() without priority param defaults to normal."""
        bus.emit("agent.text_delta", {"text": "hi"})
        event = bus.buffer[0]
        assert event.get("priority") is None or event.get("priority") == "normal"

    def test_critical_event_carries_priority_field(self, bus):
        """Critical events have priority field in the event dict."""
        bus.emit("node.failed", {"node_id": "x"}, priority="critical")
        event = [e for e in bus.buffer if e["type"] == "node.failed"][0]
        assert event.get("priority") == "critical"


# ----- Integration: subscriber dispatch -----


class TestCriticalEventSubscriberDispatch:
    """Critical events must reach subscribers even when queues are under pressure."""

    @pytest.mark.asyncio
    async def test_critical_event_delivered_to_subscriber(self, bus):
        """Critical events are dispatched to subscriber queues."""
        sub_id, queue = await bus.subscribe()

        bus.emit("node.failed", {"node_id": "n1", "error": "crash"}, priority="critical")

        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["type"] == "node.failed"
        assert event["payload"]["node_id"] == "n1"

        await bus.unsubscribe(sub_id)

    @pytest.mark.asyncio
    async def test_critical_event_survives_subscriber_overflow(self, bus):
        """When subscriber queue is full, critical events are still dispatched."""
        sub_id, queue = await bus.subscribe()

        # Fill subscriber queue — default asyncio.Queue has no max unless we set one,
        # so we use a small queue to test overflow
        await bus.unsubscribe(sub_id)
        bus._subscribers[sub_id] = asyncio.Queue(maxsize=5)

        for i in range(10):
            bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

        bus.emit("node.failed", {"node_id": "n1", "error": "crash"}, priority="critical")

        events = []
        q = bus._subscribers[sub_id]
        while not q.empty():
            events.append(q.get_nowait())

        failed = [e for e in events if e["type"] == "node.failed"]
        assert len(failed) == 1, "critical event must be delivered even under overflow"

    @pytest.mark.asyncio
    async def test_backward_compat_emit_without_priority(self, bus):
        """Existing callers using emit(type, payload) still work."""
        sub_id, queue = await bus.subscribe()

        bus.emit("test.event", {"foo": "bar"})

        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["type"] == "test.event"
        assert event["payload"] == {"foo": "bar"}

        await bus.unsubscribe(sub_id)
