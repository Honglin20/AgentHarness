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

    ``iter_index`` is the iter metadata source of truth (ADR D1). The
    function auto-fills it from ``RunStore.get_iter_index(workflow_id)``
    when the caller doesn't pass it — every caller (final-save in
    server/runner.py and cli_runner.py, plus the incremental_save path)
    needs the same data, so making them all remember to pass it is a
    fragile interface. When the RunStore has nothing either,
    ``compute_outline`` falls back to synthesizing iter=1 per DAG node.

    Wrapped in try/except: a buggy projection must NEVER block the caller's
    own save (which has already succeeded by the time this is called in the
    final-save path, and is the primary intent in the incremental-save
    path). On failure the sidecar is simply not written, ``_has_outline``
    stays False, and the frontend falls back to deriving from conversation.
    """
    try:
        from harness.run_store import get_run_store

        if iter_index is None:
            try:
                iter_index = get_run_store().get_iter_index(workflow_id) or None
            except Exception:
                logger.debug(
                    "Could not load iter_index for %s — falling back to single-iter outline",
                    workflow_id,
                    exc_info=True,
                )
                iter_index = None

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
