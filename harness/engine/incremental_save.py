"""Best-effort incremental persistence after each node completes.

Persists ``agent_io`` + derived conversation to disk so that switching to a
running workflow always fetches authoritative data from backend. Never
raises — if save fails, the workflow continues normally.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness.engine.builder import MacroGraphBuilder

logger = logging.getLogger(__name__)


def _save_incremental(
    builder: "MacroGraphBuilder",
    event_bus: Any,
    node_id: str | None = None,
    iter_num: int | None = None,
    duration_ms: int | None = None,
    status: str = "completed",
) -> None:
    """Persist agent_io + derived conversation to RunStore.

    Imports RunStore / ChartCollector / repository lazily so this module
    stays free of the server-side import graph (engine should not depend
    on server at module load time).

    Also maintains:
      - latest-state snapshot sidecar (long-run replay O(1) refresh)
      - per-iter sidecar + iter_index (Phase 2 cycle iter persistence)

    When `node_id` + `iter_num` are provided, writes a per-iter sidecar
    carrying that invocation's input/output/duration, and updates the
    iter_index so the frontend iter dropdown can render without loading
    every sidecar.

    See docs/plans/2026-06-16-long-run-replay-architecture.md.
    """
    try:
        from harness.run_store import get_run_store
        from harness.extensions.collectors import build_conversation, ChartCollector
        from server.repository import get_repository

        wid = builder.workflow_id
        if not wid:
            return

        repo = get_repository()
        data = repo.get(wid)
        if not data or not data.get("workflow"):
            return

        conversation_full = build_conversation(dict(builder.agent_io))

        chart_groups = None
        if event_bus:
            cc = ChartCollector(event_bus)
            cg = cc.get_chart_groups()
            if cg.get("groupOrder"):
                chart_groups = cg

        dag = repo.get_dag(wid)
        agent_io_snapshot = dict(builder.agent_io)
        todo_snapshot = dict(builder.todo_states) or None

        get_run_store().save(
            run_id=wid,
            workflow_name=data["workflow"].name,
            agents_snapshot=data.get("agents_snapshot", []),
            status="running",
            inputs=data.get("inputs", {}),
            result=None,
            dag=dag,
            agent_io=agent_io_snapshot,
            batch_id=data.get("batch_id"),
            user_id=data.get("user_id"),
            conversation=conversation_full,
            chart_groups=chart_groups,
            created_at=data.get("created_at"),
            work_dir=data.get("work_dir"),
            todo_steps=todo_snapshot,
        )

        # Per-iter sidecar (Phase 2). Skip when caller didn't pass
        # invocation info (defensive — every callsite should pass it).
        if node_id is not None and iter_num is not None:
            node_io = agent_io_snapshot.get(node_id) or {}
            output_result = node_io.get("output_result") if isinstance(node_io, dict) else None
            iter_data = {
                "iter": iter_num,
                "node_id": node_id,
                "status": status,
                "duration_ms": duration_ms,
                "input_prompt": node_io.get("input_prompt") if isinstance(node_io, dict) else None,
                "system_prompt": node_io.get("system_prompt") if isinstance(node_io, dict) else None,
                "output": output_result,
                # Short summary for iter dropdown — extract from common shapes.
                "summary": _extract_iter_summary(output_result),
                # Phase 3 fills events_seq_range by intersecting event seqs
                # with iter boundaries; for now, omit.
            }
            try:
                get_run_store().save_iter_sidecar(wid, node_id, iter_num, iter_data)
                get_run_store().update_iter_index(wid, node_id, {
                    "iter": iter_num,
                    "status": status,
                    "duration_ms": duration_ms,
                    "summary": iter_data["summary"],
                })
            except Exception:
                logger.warning(
                    "Iter sidecar save failed for %s/%s/iter=%s — iter UI will miss this entry",
                    wid, node_id, iter_num,
                    exc_info=True,
                )

        # Latest-state snapshot — O(1) refresh payload for long-run replay.
        # conversation_tail keeps the snapshot small (Phase 2 optimization):
        # long runs accumulated >700KB snapshot because conversation grew
        # unbounded. Tail of 50 keeps the snapshot ~50KB regardless of run
        # length; older messages load via /api/runs/{id}/conversation pagination.
        conversation_tail = conversation_full[-50:] if len(conversation_full) > 50 else conversation_full

        # iter_index snapshot mirror — lets the frontend render the iter
        # dropdown without an extra API call on initial hydrate.
        try:
            iter_index = get_run_store().get_iter_index(wid) or {}
        except Exception:
            iter_index = {}

        # current_iter: max iter seen across all cycle agents. None if no
        # iter sidecars written yet (setup-only / Phase 1 run).
        current_iter = None
        for entries in iter_index.values():
            for e in entries:
                if isinstance(e.get("iter"), int):
                    if current_iter is None or e["iter"] > current_iter:
                        current_iter = e["iter"]

        snapshot = {
            "run_id": wid,
            "workflow_name": data["workflow"].name,
            "status": "running",
            "created_at": data.get("created_at"),
            "seq_cursor": getattr(event_bus, "_seq", 0),
            "dag": dag,
            "agent_io": agent_io_snapshot,
            # Tail-only — full conversation via sidecar pagination.
            "conversation": conversation_tail,
            "charts": chart_groups,
            "todo_states": todo_snapshot,
            "nodes_latest": {
                nid: {
                    "status": "completed",
                    # Attach latest iter num for this node so the DAG UI can
                    # show "iter 7 (latest)" without an extra API call.
                    "latest_iter": max(
                        (e["iter"] for e in iter_index.get(nid, []) if isinstance(e.get("iter"), int)),
                        default=None,
                    ),
                }
                for nid in agent_io_snapshot.keys()
            },
            # Phase 2 fields.
            "current_iter": current_iter,
            "iter_index": iter_index,
            # Phase 4: NAS fitness series extracted from judger agent_io.
            "fitness_history": [],
        }
        try:
            get_run_store().save_snapshot(wid, snapshot)
        except Exception:
            # Snapshot failure must not block the main save — log and move on.
            # Frontend will fall back to the legacy replay path for this run.
            logger.warning(
                "Snapshot save failed for workflow %s — frontend will replay",
                wid,
                exc_info=True,
            )
    except Exception:
        logger.exception("Incremental save failed for workflow %s", wid)


def _extract_iter_summary(output: Any, max_len: int = 120) -> str:
    """Best-effort short summary for an iter dropdown entry.

    Handles common output shapes: dict with 'summary' field, dict with
    'decision', raw string, etc. Falls back to truncated repr.
    """
    if output is None:
        return ""
    if isinstance(output, str):
        s = output.strip().split("\n", 1)[0]
        return s[:max_len] + ("…" if len(s) > max_len else "")
    if isinstance(output, dict):
        for key in ("summary", "decision", "reason", "outcome"):
            v = output.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:max_len] + ("…" if len(v) > max_len else "")
        # Fall through to repr
    try:
        s = str(output)
        return s[:max_len] + ("…" if len(s) > max_len else "")
    except Exception:
        return ""
