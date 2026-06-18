"""I/O wrapper that computes and persists the outline summary sidecar.

Lives outside ``outline_compute.py`` (which is pure / no I/O) so the pure
projection stays unit-testable without touching disk. Both the final-save
path (``server/runner.py``) and the incremental-save path
(``harness/engine/incremental_save.py``) call this — that's the whole
point: incremental saves during long NAS runs need to keep the outline
sidecar fresh, because final-save only fires on workflow completion and
may never fire for interrupted / cancelled runs.

Best-effort by design: failures are logged but never propagated. A buggy
projection must not block the parent save (main record / snapshot).
"""
from __future__ import annotations

import logging
from typing import Any

from harness.persistence.outline_compute import compute_outline

logger = logging.getLogger(__name__)


def save_outline_sidecar(
    *,
    workflow_id: str,
    conversation: list[dict] | None,
    events: list[dict] | None,
    trace: list[dict] | None,
    todo_steps: dict | None,
    agents_snapshot: list[dict] | None,
    dag: dict | None,
    iter_index: dict[str, list[dict]] | None = None,
) -> None:
    """Compute the outline projection and persist it as ``{run_id}+outline.json``.

    ``iter_index`` is the iter metadata source of truth (ADR D1). Caller
    should pass ``RunStore.get_iter_index(workflow_id)`` so the outline
    reflects the actual on-disk iter set. When None, ``compute_outline``
    falls back to synthesizing iter=1 per DAG node.

    Wrapped in try/except: a buggy projection must NEVER block the caller's
    own save (which has already succeeded by the time this is called in the
    final-save path, and is the primary intent in the incremental-save
    path). On failure the sidecar is simply not written, ``_has_outline``
    stays False, and the frontend falls back to deriving from conversation.
    """
    try:
        from harness.run_store import get_run_store

        outline = compute_outline(
            conversation=conversation,
            events=events,
            trace=trace,
            todo_steps=todo_steps,
            agents_snapshot=agents_snapshot,
            dag=dag,
            iter_index=iter_index,
        )
        if outline:
            get_run_store().save_outline(workflow_id, outline)
    except Exception:
        logger.exception(
            "outline sidecar computation failed for %s — falling back to frontend derive",
            workflow_id,
        )
