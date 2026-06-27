"""Rebuild main record's conversation from per-iter sidecars.

Transitional module — remove when ADR D4 ("single-source-index-driven") fully
lands (frontend stops reading main record's conversation field). Until then,
this provides a complete view in main_record.conversation by sourcing from
the authoritative per-iter sidecars instead of the lossy Bus buffer projection
(which FIFO-evicts early events on long runs).

See plans/buzzing-bouncing-reef.md for context.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def rebuild_conversation_from_sidecars(
    run_id: str,
    agent_io: dict[str, dict] | None,
) -> list[dict]:
    """Rebuild conversation messages from per-iter sidecars.

    Walks ``iter_index`` to find every (node, iter) pair that ran, reads each
    sidecar from disk, and feeds the assembled ``sidecar_data`` to
    ``build_conversation`` — which already knows how to project sidecars +
    agent_io into the frontend's ConversationMessage shape (including
    thinking, tool_streaming_outputs, and multi-iter history).

    Args:
        run_id: The run id.
        agent_io: Per-node io_data (output_result / tool_calls / input_prompt).
            Pass ``{}`` when caller has none; ``build_conversation`` degrades
            gracefully and produces output purely from sidecars.

    Returns:
        List of ConversationMessage-shaped dicts. Empty list when:

          - iter_index sidecar is absent (legacy / setup-only / pre-P2a runs)
          - all sidecar reads failed
          - any unexpected exception — caller should fall back to the
            ConversationCollector Bus-buffer projection.

    The empty-list contract is load-bearing: callers use ``if not
    conversation: <fallback>`` to decide. Never raises.
    """
    try:
        from harness.extensions.collectors import build_conversation
        from harness.run_store import get_run_store

        store = get_run_store()
        iter_index = store.get_iter_index(run_id)
        if not iter_index:
            return []

        sidecar_data: dict[str, list[dict]] = {}
        for node_id, iter_entries in iter_index.items():
            if not isinstance(iter_entries, list):
                continue
            node_sidecars: list[dict] = []
            for entry in iter_entries:
                if not isinstance(entry, dict):
                    continue
                iter_num = entry.get("iter")
                if not isinstance(iter_num, int):
                    continue
                try:
                    sidecar = store.get_iter_sidecar(run_id, node_id, iter_num)
                except Exception:
                    logger.warning(
                        "rebuild: failed to read sidecar %s/%s/iter=%s — skipped",
                        run_id, node_id, iter_num,
                        exc_info=True,
                    )
                    sidecar = None
                if sidecar is not None:
                    node_sidecars.append(sidecar)
            if node_sidecars:
                sidecar_data[node_id] = node_sidecars

        if not sidecar_data:
            return []

        return build_conversation(
            agent_io or {},
            sidecar_data=sidecar_data,
        )
    except Exception:
        logger.warning(
            "rebuild_conversation_from_sidecars failed for %s — caller should "
            "fall back to ConversationCollector",
            run_id,
            exc_info=True,
        )
        return []
