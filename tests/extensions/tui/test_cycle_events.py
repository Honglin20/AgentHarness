"""Tests for cycle_events.py — optional iteration contract for workflows.

Workflows that own their iteration loop (NAS, evolutionary search, etc.)
emit cycle.start/end so the TUI sidebar can show "iter N/M" + a fitness
sparkline. Workflows that don't emit leave the sidebar showing "—".

The events are NOT in CRITICAL_EVENT_TYPES (per bus.py:50 rule) — they're
a presentation hint, not state the UI depends on for correctness.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from harness.extensions.tui.cycle_events import (
    CYCLE_END_EVENT,
    CYCLE_START_EVENT,
    IterationContext,
    emit_cycle_end,
    emit_cycle_start,
)


class _BusStub:
    """Minimal bus stub recording emit() calls."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


# ---------------------------------------------------------------------------
# emit_cycle_start / emit_cycle_end
# ---------------------------------------------------------------------------


def test_emit_cycle_start_writes_payload():
    bus = _BusStub()
    emit_cycle_start(bus, iter_num=1, total=10)
    assert bus.calls == [(CYCLE_START_EVENT, {"iter": 1, "total": 10})]


def test_emit_cycle_start_with_extra_fields():
    bus = _BusStub()
    emit_cycle_start(bus, iter_num=3, total=10, extra={"phase": "search"})
    assert bus.calls[0][0] == CYCLE_START_EVENT
    assert bus.calls[0][1]["phase"] == "search"
    assert bus.calls[0][1]["iter"] == 3


def test_emit_cycle_end_writes_score():
    bus = _BusStub()
    emit_cycle_end(bus, iter_num=2, score=0.85, total=10)
    assert bus.calls == [
        (CYCLE_END_EVENT, {"iter": 2, "score": 0.85, "total": 10})
    ]


def test_emit_cycle_end_with_extra_fields():
    bus = _BusStub()
    emit_cycle_end(
        bus,
        iter_num=5,
        score=0.92,
        extra={"latency_ms": 12.3, "strategy_id": "cnn_v3"},
    )
    payload = bus.calls[0][1]
    assert payload["score"] == 0.92
    assert payload["latency_ms"] == 12.3
    assert payload["strategy_id"] == "cnn_v3"


def test_emit_cycle_with_no_total():
    """Open-ended search (no known total) must still emit — total simply
    omitted so sidebar shows just 'iter N' without the /M suffix."""
    bus = _BusStub()
    emit_cycle_start(bus, iter_num=7)
    emit_cycle_end(bus, iter_num=7, score=0.4)
    assert "total" not in bus.calls[0][1]
    assert "total" not in bus.calls[1][1]


def test_emit_cycle_with_none_bus_is_noop():
    """Plain Python script with no bus — helpers must not crash."""
    emit_cycle_start(None, iter_num=1, total=5)
    emit_cycle_end(None, iter_num=1, score=0.5)


def test_emit_cycle_end_score_coerced_to_float():
    """Workflows may pass numpy floats / Decimals; emit converts."""
    bus = _BusStub()
    emit_cycle_end(bus, iter_num=1, score=0.71)  # already float
    emit_cycle_end(bus, iter_num=2, score=1)  # int
    assert isinstance(bus.calls[0][1]["score"], float)
    assert bus.calls[0][1]["score"] == 0.71
    assert bus.calls[1][1]["score"] == 1.0


def test_emit_cycle_iter_coerced_to_int():
    bus = _BusStub()
    emit_cycle_start(bus, iter_num=2.0)  # float
    emit_cycle_end(bus, iter_num=3.0, score=0.5)
    assert bus.calls[0][1]["iter"] == 2
    assert isinstance(bus.calls[0][1]["iter"], int)
    assert bus.calls[1][1]["iter"] == 3


# ---------------------------------------------------------------------------
# IterationContext helper
# ---------------------------------------------------------------------------


def test_iteration_context_advance_tracks_best():
    ctx = IterationContext(total=5)
    assert ctx.current == 0
    assert ctx.best_score is None

    ctx.advance(score=0.5)
    assert ctx.current == 1
    assert ctx.best_score == 0.5

    ctx.advance(score=0.3)
    assert ctx.current == 2
    assert ctx.best_score == 0.5  # not bested

    ctx.advance(score=0.9)
    assert ctx.current == 3
    assert ctx.best_score == 0.9  # new best


def test_iteration_context_advance_without_score():
    """Search workflows may finish a cycle before scoring — advance
    should still bump current."""
    ctx = IterationContext(total=10)
    ctx.advance()
    ctx.advance()
    assert ctx.current == 2
    assert ctx.best_score is None  # untouched


def test_iteration_context_metadata_default_is_empty_dict():
    ctx = IterationContext()
    assert ctx.metadata == {}
    ctx.metadata["last_strategy"] = "resnet"
    assert ctx.metadata["last_strategy"] == "resnet"


# ---------------------------------------------------------------------------
# Integration: emit + SidebarPanel.on_cycle_end
# ---------------------------------------------------------------------------


def test_cycle_end_event_feeds_sidebar_panel():
    """End-to-end: emit_cycle_end → bus → sidebar reads event payload.

    Locks the payload schema so workflows emitting via the helper are
    guaranteed to produce what SidebarPanel.on_cycle_end expects.
    """
    from harness.extensions.tui.sidebar import SidebarPanel

    bus = _BusStub()
    sb = SidebarPanel()

    # Workflow emits
    emit_cycle_end(bus, iter_num=1, score=0.5, total=10)
    emit_cycle_end(bus, iter_num=2, score=0.7, total=10)

    # Sidebar reads (in production this goes through the bus subscriber;
    # here we replay directly to verify schema compatibility)
    for event_type, payload in bus.calls:
        sb.on_cycle_end(payload)

    assert sb.state.fitness_history == [0.5, 0.7]
    assert sb.state.current_iter == 2
    assert sb.state.total_iters == 10
