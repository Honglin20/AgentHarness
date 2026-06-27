"""P2-T2: agent.executor_error criticality acceptance tests.

Locks the contract that ``agent.executor_error`` is in
``CRITICAL_EVENT_TYPES`` so the WS replay buffer never FIFO-evicts it.
Losing this event permanently corrupts the frontend's failure display
(no way to reconstruct WHY a node failed even after refresh).
"""
from __future__ import annotations

import pytest

from harness.extensions.bus import CRITICAL_EVENT_TYPES, _resolve_priority


def test_executor_error_is_critical():
    """agent.executor_error MUST be whitelisted so the WS replay buffer
    keeps it across arbitrary event volume (long NAS runs emit thousands
    of agent.text_delta events that would otherwise evict it)."""
    assert "agent.executor_error" in CRITICAL_EVENT_TYPES


def test_executor_error_auto_resolves_to_critical():
    """safe_emit with priority=None (the default) must auto-promote
    agent.executor_error to critical via the whitelist."""
    assert _resolve_priority("agent.executor_error", None) == "critical"


def test_executor_error_explicit_normal_overrides_whitelist():
    """Explicit priority='normal' must override the whitelist — escape
    hatch for sinks that intentionally want eviction (none currently,
    but the contract must hold for symmetry with other critical events)."""
    assert _resolve_priority("agent.executor_error", "normal") == "normal"


def test_executor_error_explicit_invalid_priority_raises():
    """A typo'd priority like 'critcal' must fail loud at the call site
    rather than silently demote a critical event to normal."""
    with pytest.raises(ValueError, match="Invalid priority"):
        _resolve_priority("agent.executor_error", "critcal")


@pytest.mark.parametrize("critical_event", [
    "workflow.started",
    "workflow.completed",
    "workflow.error",
    "workflow.cancelled",
    "node.started",
    "node.completed",
    "node.failed",
    "agent.failed_with_classified_reason",
    "agent.executor_error",
])
def test_canonical_critical_set_unchanged(critical_event):
    """Regression guard: the canonical critical set documented in the plan
    must remain whitelisted. Catches accidental removal during refactors."""
    assert critical_event in CRITICAL_EVENT_TYPES
