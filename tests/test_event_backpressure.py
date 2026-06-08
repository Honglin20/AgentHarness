"""Test event pipeline backpressure — slow consumers shouldn't cause OOM."""
import asyncio
import pytest
from harness.extensions.bus import Bus


def test_buffer_usage_empty():
    bus = Bus(buffer_size=100)
    assert bus.buffer_usage() == 0.0


def test_buffer_usage_half():
    bus = Bus(buffer_size=10)
    for i in range(5):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})
    assert 0.4 <= bus.buffer_usage() <= 0.6


def test_buffer_usage_full():
    bus = Bus(buffer_size=10)
    for i in range(15):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})
    assert bus.buffer_usage() >= 1.0


def test_subscriber_queue_bounded():
    """When subscriber_queue_size is set, queue should not grow unbounded."""
    bus = Bus(buffer_size=100, subscriber_queue_size=5)
    # Manually add a subscriber with bounded queue
    sub_id = "test-sub"
    bus._subscribers[sub_id] = asyncio.Queue(maxsize=5)
    for i in range(50):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

    q = bus._subscribers[sub_id]
    assert q.qsize() <= 10  # bounded, not 50


def test_subscriber_queue_unbounded_default():
    """Default (subscriber_queue_size=0) means unbounded queue."""
    bus = Bus(buffer_size=100)
    sub_id = "test-sub"
    bus._subscribers[sub_id] = asyncio.Queue()
    for i in range(50):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

    q = bus._subscribers[sub_id]
    assert q.qsize() == 50


def test_buffer_size_limit_respected():
    """Internal buffer should not exceed configured size significantly."""
    bus = Bus(buffer_size=10)
    for i in range(100):
        bus.emit("agent.text_delta", {"text": f"chunk-{i}"})

    buffered = bus.buffer
    normal = [e for e in buffered if e.get("priority") != "critical"]
    assert len(normal) <= 15
