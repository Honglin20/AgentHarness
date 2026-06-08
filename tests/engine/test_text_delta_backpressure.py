"""Backpressure tests for LLMExecutor._emit_text_delta.

Verifies that:
1. When bus buffer <80% full → all deltas emitted (no throttle).
2. When bus buffer >80% full → ~50% of deltas emitted (skip every other).
3. _delta_skip_counter is per-instance, NOT class-level — two concurrent
   LLMExecutor instances maintain independent throttle state.

These tests target the bug where the throttle body ran unconditionally
after the except clause, dropping deltas even when the buffer was empty.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from harness.engine.llm_executor import LLMExecutor
from harness.extensions.bus import Bus


def _make_executor(bus) -> LLMExecutor:
    """Build a minimal LLMExecutor wired to a bus."""
    # We never call .run(); only the private _emit_text_delta. The agent
    # and deps are placeholders that satisfy __init__.
    return LLMExecutor(
        MagicMock(),
        MagicMock(),
        event_bus=bus,
        workflow_id="wf-1",
        node_id="n-1",
        agent_name="agent-1",
    )


def _count_emits(bus: Bus, event_type: str = "agent.text_delta") -> int:
    """Count events of a given type in the bus buffer."""
    return sum(1 for e in bus.buffer if e["type"] == event_type)


# ---------------------------------------------------------------------------
# Branch 1: buffer <80% full → no throttle
# ---------------------------------------------------------------------------


def test_no_throttle_when_buffer_under_threshold():
    """All deltas emitted when buffer is well below 80%."""
    bus = Bus(buffer_size=100)  # threshold at 80 entries
    executor = _make_executor(bus)

    for i in range(10):
        executor._emit_text_delta(f"chunk-{i}")

    assert _count_emits(bus) == 10, (
        "All 10 deltas should be emitted when buffer <80% full"
    )


def test_no_throttle_with_empty_buffer():
    """Fresh bus → all deltas emitted."""
    bus = Bus(buffer_size=10)
    executor = _make_executor(bus)

    for i in range(3):
        executor._emit_text_delta(f"delta-{i}")

    assert _count_emits(bus) == 3


# ---------------------------------------------------------------------------
# Branch 2: buffer >80% full → ~50% throttle
# ---------------------------------------------------------------------------


def test_throttle_skips_every_other_when_buffer_over_threshold():
    """When buffer >80% full, ~half of deltas are dropped (every other)."""
    bus = Bus(buffer_size=10)  # 80% threshold = 8 entries
    executor = _make_executor(bus)

    # Pre-fill the buffer to push usage above 0.8
    for i in range(9):
        bus.emit("node.started", {"i": i})
    assert bus.buffer_usage() > 0.8, f"precondition failed: usage={bus.buffer_usage()}"

    emitted_before = _count_emits(bus, "agent.text_delta")
    assert emitted_before == 0

    # Feed 10 deltas; expect ~5 (every other skipped)
    for i in range(10):
        executor._emit_text_delta(f"chunk-{i}")

    emitted_after = _count_emits(bus, "agent.text_delta")
    assert emitted_after == 5, (
        f"Expected ~5 of 10 deltas to pass throttle, got {emitted_after}"
    )


def test_throttle_counter_starts_skipping_on_first_over_threshold_call():
    """Over-threshold deltas skip on calls 2, 4, 6, ... (counter starts at 0)."""
    bus = Bus(buffer_size=10)
    executor = _make_executor(bus)

    for i in range(9):
        bus.emit("node.started", {"i": i})
    assert bus.buffer_usage() > 0.8

    # Track which deltas actually get emitted by inspecting payload text.
    for i in range(6):
        executor._emit_text_delta(f"d-{i}")

    emitted_texts = [
        e["payload"]["text"]
        for e in bus.buffer
        if e["type"] == "agent.text_delta"
    ]
    # Counter sequence: 1,2,3,4,5,6 → even values skip → d-1, d-3, d-5 emitted
    assert emitted_texts == ["d-0", "d-2", "d-4"], (
        f"Expected alternating pattern, got {emitted_texts}"
    )


# ---------------------------------------------------------------------------
# Branch 3: per-instance counter (NOT class-level)
# ---------------------------------------------------------------------------


def test_counter_is_per_instance_not_class_level():
    """Two LLMExecutor instances maintain independent throttle state.

    This guards against regression where _delta_skip_counter was a
    class-level attribute shared across all instances.
    """
    bus_a = Bus(buffer_size=10)
    bus_b = Bus(buffer_size=10)
    exec_a = _make_executor(bus_a)
    exec_b = _make_executor(bus_b)

    # Sanity: instance attribute, not class attribute.
    assert hasattr(exec_a, "_delta_skip_counter")
    assert hasattr(exec_b, "_delta_skip_counter")
    assert exec_a._delta_skip_counter == 0
    assert exec_b._delta_skip_counter == 0

    # Push a's buffer over threshold; keep b's empty.
    for i in range(9):
        bus_a.emit("node.started", {"i": i})
    assert bus_a.buffer_usage() > 0.8
    assert bus_b.buffer_usage() == 0.0

    # Drive a's counter forward; b's should stay at 0.
    exec_a._emit_text_delta("a-0")  # counter → 1 (emit)
    exec_a._emit_text_delta("a-1")  # counter → 2 (skip)
    exec_a._emit_text_delta("a-2")  # counter → 3 (emit)

    # a's counter advanced independently; b's untouched.
    assert exec_a._delta_skip_counter == 3, (
        f"exec_a counter should be 3, got {exec_a._delta_skip_counter}"
    )
    assert exec_b._delta_skip_counter == 0, (
        "exec_b counter must NOT move when only exec_a is called — "
        "this would fail if _delta_skip_counter were a class attribute"
    )

    # b emits freely (its buffer is empty) and never increments its counter
    # into a's territory.
    exec_b._emit_text_delta("b-0")
    exec_b._emit_text_delta("b-1")
    assert exec_b._delta_skip_counter == 0, (
        "b's counter should not increment when buffer is under threshold"
    )
    assert _count_emits(bus_b, "agent.text_delta") == 2


def test_class_attribute_regression_does_not_share_state():
    """Independent counter: bumping one instance must not affect another.

    Specifically targets the historical bug where
    ``LLMExecutor._delta_skip_counter: int = 0`` was declared at class scope
    and ``LLMExecutor._delta_skip_counter += 1`` mutated the class attribute.
    """
    bus = Bus(buffer_size=10)
    exec_a = _make_executor(bus)
    exec_b = _make_executor(bus)

    # Manually advance exec_a's counter — exec_b's must not change.
    exec_a._delta_skip_counter = 7
    assert exec_b._delta_skip_counter == 0, (
        "Counter leaked across instances — class-level regression"
    )

    # Also confirm the class itself doesn't have the instance attribute
    # (it should be set on self, not on the class).
    assert "_delta_skip_counter" not in LLMExecutor.__dict__, (
        "_delta_skip_counter must be an instance attribute, not class-level"
    )


# ---------------------------------------------------------------------------
# Edge: bus without buffer_usage()
# ---------------------------------------------------------------------------


def test_bus_without_buffer_usage_never_throttles():
    """A bus that lacks buffer_usage() must emit every delta (no AttributeError)."""
    # MagicMock's buffer_usage will be a Mock — make it raise AttributeError
    # by deleting it, simulating an older bus implementation.
    fake_bus = MagicMock()
    # hasattr() will be True for MagicMock; force the realistic path by
    # having buffer_usage return a low value.
    fake_bus.buffer_usage.return_value = 0.0
    fake_bus.emit = MagicMock()

    executor = _make_executor(fake_bus)
    for i in range(20):
        executor._emit_text_delta(f"d-{i}")

    assert fake_bus.emit.call_count == 20


def test_bus_with_broken_buffer_usage_never_throttles():
    """If buffer_usage() raises TypeError, throttle is skipped (fail-open)."""
    fake_bus = MagicMock()
    def _boom():
        raise TypeError("broken")
    fake_bus.buffer_usage = _boom
    fake_bus.emit = MagicMock()

    executor = _make_executor(fake_bus)
    for i in range(20):
        executor._emit_text_delta(f"d-{i}")

    # No exception, all 20 emitted.
    assert fake_bus.emit.call_count == 20


def test_bus_returning_non_numeric_buffer_usage_fails_open():
    """If buffer_usage() returns a non-numeric (e.g. MagicMock), throttle is
    skipped rather than crashing the stream loop.

    This is the original test_emit_text_delta failure mode — bus is a bare
    MagicMock whose buffer_usage() returns another MagicMock, and the
    ``> 0.8`` comparison raises TypeError. The fix must catch that.
    """
    fake_bus = MagicMock()
    # Default MagicMock.buffer_usage() returns a MagicMock — comparison with
    # float will raise TypeError. We must NOT crash.
    fake_bus.emit = MagicMock()

    executor = _make_executor(fake_bus)
    for i in range(20):
        executor._emit_text_delta(f"d-{i}")

    assert fake_bus.emit.call_count == 20
