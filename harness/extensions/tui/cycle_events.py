"""Optional cycle event contract for iterative workflows.

Workflows that iterate (NAS candidate search, evolutionary optimizers,
multi-round refinement) can emit ``cycle.start`` / ``cycle.end`` events
to give the TUI sidebar a fitness sparkline and an iteration counter
("iter N/M"). Workflows that don't iterate leave the sidebar showing
"—" (SidebarPanel graceful-degrade path).

Design decisions
----------------
- **Not** in ``CRITICAL_EVENT_TYPES`` (per ``harness/extensions/bus.py``
  rule: critical is reserved for "miss this and the UI is permanently
  wrong"). Cycle is a presentation hint; sidebar shows "—" without it.
- Emitted via the normal bus path so the events sidecar captures them
  for replay. The frontend's existing FitnessChart (which already reads
  per-node judger output for NAS) is unaffected — these events are an
  opt-in addition for CLI visualization, not a replacement.
- Helper functions live here rather than inline in workflows so the
  payload schema is in one place. Workflows that already emit fitness
  via judger output continue to work; ``emit_cycle_end`` is the generic
  alternative for non-judger-based cycles.

Usage
-----
.. code-block:: python

    from harness.extensions.tui.cycle_events import (
        IterationContext, emit_cycle_start, emit_cycle_end,
    )

    # In a workflow that owns its iteration loop:
    ctx = IterationContext(total=10)
    for i in range(10):
        emit_cycle_start(bus, i + 1, total=10)
        # ... run cycle agents ...
        score = await evaluate(...)
        emit_cycle_end(bus, i + 1, score, total=10)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Event type constants — published so test fixtures and workflow authors
# import from one place rather than spelling the string everywhere.
CYCLE_START_EVENT = "cycle.start"
CYCLE_END_EVENT = "cycle.end"


@dataclass
class IterationContext:
    """Optional bookkeeping helper for workflows that own their loops.

    The TUI doesn't read this — it just reads the events emitted via
    ``emit_cycle_start`` / ``emit_cycle_end``. This dataclass is for
    workflow authors who want a single object tracking iter/total/score
    across agent boundaries without re-plumbing the LangGraph state.
    """

    total: Optional[int] = None
    current: int = 0
    best_score: Optional[float] = None
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def advance(self, score: Optional[float] = None) -> int:
        """Call once per cycle to bump current; tracks best_score."""
        self.current += 1
        if score is not None:
            if self.best_score is None or score > self.best_score:
                self.best_score = score
        return self.current


def emit_cycle_start(
    bus,
    iter_num: int,
    total: Optional[int] = None,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Emit ``cycle.start`` so the TUI sidebar can show "iter N/M".

    No-op if ``bus`` is None (plain Python script with no event bus).

    Args:
        bus: EventBus / Bus instance. Pass None for safe no-op.
        iter_num: 1-indexed cycle number.
        total: Total expected cycles. None when unknown (open-ended search).
        extra: Optional extra payload fields (e.g. strategy_id, phase).
    """
    if bus is None:
        return
    payload: dict[str, Any] = {"iter": int(iter_num)}
    if total is not None:
        payload["total"] = int(total)
    if extra:
        payload.update(extra)
    bus.emit(CYCLE_START_EVENT, payload)


def emit_cycle_end(
    bus,
    iter_num: int,
    score: float,
    total: Optional[int] = None,
    *,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Emit ``cycle.end`` with the cycle's score. Sidebar reads ``score``
    to drive its sparkline and tracks ``iter`` / ``total`` for the
    "iter N/M" counter.

    Args:
        bus: EventBus / Bus instance. Pass None for safe no-op.
        iter_num: 1-indexed cycle number.
        score: Cycle's fitness / accuracy / whatever scalar the workflow
            is optimizing. Higher is better (used to compute "best").
        total: Total expected cycles. None when unknown.
        extra: Optional extra payload (e.g. latency_ms, strategy_id).
    """
    if bus is None:
        return
    payload: dict[str, Any] = {
        "iter": int(iter_num),
        "score": float(score),
    }
    if total is not None:
        payload["total"] = int(total)
    if extra:
        payload.update(extra)
    bus.emit(CYCLE_END_EVENT, payload)
