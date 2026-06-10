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
    """
    try:
        from harness.run_store import RunStore
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

        RunStore().save(
            run_id=wid,
            workflow_name=data["workflow"].name,
            agents_snapshot=data.get("agents_snapshot", []),
            status="running",
            inputs=data.get("inputs", {}),
            result=None,
            dag=repo.get_dag(wid),
            agent_io=dict(builder.agent_io),
            batch_id=data.get("batch_id"),
            user_id=data.get("user_id"),
            conversation=conversation,
            chart_groups=chart_groups,
            created_at=data.get("created_at"),
            work_dir=data.get("work_dir"),
            todo_steps=dict(builder.todo_states) or None,
        )
    except Exception:
        logger.exception("Incremental save failed for workflow %s", wid)
