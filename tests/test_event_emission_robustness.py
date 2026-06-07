"""Tests for safe_emit — event emission never crashes the pipeline."""

from __future__ import annotations

import pytest

from harness.extensions.bus import Bus, safe_emit


class TestSafeEmit:
    """safe_emit() wraps bus.emit() so failures never propagate."""

    def test_none_bus_does_not_crash(self):
        """safe_emit with bus=None is a silent no-op."""
        safe_emit(None, "node.started", {"node_id": "a"})
        # No exception raised — that's the entire contract.

    def test_broken_bus_does_not_crash(self):
        """safe_emit swallows exceptions from a broken bus."""
        bus = Bus()

        # Sabotage emit so it always raises.
        original_emit = bus.emit

        def _broken_emit(*args, **kwargs):
            raise RuntimeError("bus is on fire")

        bus.emit = _broken_emit  # type: ignore[assignment]

        # Should NOT raise — safe_emit catches and logs.
        safe_emit(bus, "node.started", {"node_id": "a"})

        # Restore so teardown doesn't blow up.
        bus.emit = original_emit  # type: ignore[assignment]

    def test_working_bus_actually_emits(self):
        """safe_emit delegates to bus.emit() correctly."""
        bus = Bus()
        safe_emit(bus, "node.started", {"node_id": "alpha"})
        assert len(bus.buffer) == 1
        assert bus.buffer[0]["type"] == "node.started"
        assert bus.buffer[0]["payload"]["node_id"] == "alpha"

    def test_priority_param_passed_through(self):
        """safe_emit forwards the priority kwarg to bus.emit()."""
        bus = Bus()
        safe_emit(bus, "workflow.started", {"wid": "1"}, priority="critical")
        # Bus.buffer returns critical + normal merged; check critical buffer
        all_events = bus.buffer
        assert len(all_events) == 1
        assert all_events[0]["priority"] == "critical"
        assert all_events[0]["type"] == "workflow.started"

    def test_none_payload_defaults_to_empty_dict(self):
        """safe_emit with payload=None should not crash."""
        bus = Bus()
        safe_emit(bus, "some.event", None)
        assert len(bus.buffer) == 1
        assert bus.buffer[0]["payload"] == {}
