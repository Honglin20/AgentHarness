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


def _save_incremental(builder: "MacroGraphBuilder", event_bus: Any) -> None:
    """Persist agent_io + derived conversation to RunStore.

    Imports RunStore / ChartCollector / repository lazily so this module
    stays free of the server-side import graph (engine should not depend
    on server at module load time).

    Also maintains the latest-state snapshot sidecar (long-run replay O(1)
    refresh). The snapshot is self-contained so the frontend can hydrate
    from a single GET /api/runs/{id}/snapshot without replaying the bus
    buffer. See docs/plans/2026-06-16-long-run-replay-architecture.md.
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

        conversation = build_conversation(dict(builder.agent_io))

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
            conversation=conversation,
            chart_groups=chart_groups,
            created_at=data.get("created_at"),
            work_dir=data.get("work_dir"),
            todo_steps=todo_snapshot,
        )

        # Latest-state snapshot — O(1) refresh payload for long-run replay.
        # Per-node latest invocation status is derived from agent_io keys
        # (only completed nodes appear there). Cycle iter tracking + fitness
        # history land in Phase 2; Phase 1 ships structural foundation only.
        snapshot = {
            "run_id": wid,
            "workflow_name": data["workflow"].name,
            "status": "running",
            "created_at": data.get("created_at"),
            "seq_cursor": getattr(event_bus, "_seq", 0),
            "dag": dag,
            "agent_io": agent_io_snapshot,
            "conversation": conversation,
            "charts": chart_groups,
            "todo_states": todo_snapshot,
            "nodes_latest": {
                node_id: {"status": "completed"}
                for node_id in agent_io_snapshot.keys()
            },
            # Phase 2 fills these in (cycle iter persistence + NAS fitness series).
            "current_iter": None,
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
