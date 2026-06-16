"""Best-effort incremental persistence after each node completes.

Persists ``agent_io`` + derived conversation to disk so that switching to a
running workflow always fetches authoritative data from backend. Never
raises — if save fails, the workflow continues normally.
"""
from __future__ import annotations

import json
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

        # fitness_history — NAS-specific series. Each judger completion
        # appends the iter's best fitness. Persisted across saves by reading
        # the prior snapshot's fitness_history first, so non-judger node
        # completions don't wipe it. See docs/plans/2026-06-16-long-run-replay-architecture.md Phase 4.
        try:
            prior_snapshot = get_run_store().get_snapshot(wid) or {}
            fitness_history = list(prior_snapshot.get("fitness_history") or [])
        except Exception:
            fitness_history = []

        if node_id == "judger" and iter_num is not None:
            best = _extract_best_fitness(agent_io_snapshot.get("judger"))
            if best is not None:
                # Replace any prior entry for the same iter (idempotent if
                # judger re-runs the same iter via checkpointer resume).
                fitness_history = [e for e in fitness_history if e.get("iter") != iter_num]
                fitness_history.append({"iter": iter_num, **best})
                fitness_history.sort(key=lambda e: e.get("iter", 0))

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
            # Total count of the full conversation (pre-tail). Frontend uses
            # this to set hasEarlier = (total > conversation.length) so the
            # "Load earlier" trigger knows whether to fetch.
            "conversation_total": len(conversation_full),
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
            # Phase 4: NAS fitness series. Each judger completion appends
            # one entry {iter, best_fitness, best_strategy_id, ...}. Empty
            # for non-NAS workflows or pre-judger setup phase.
            "fitness_history": fitness_history,
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


def _extract_best_fitness(judger_io: Any) -> dict | None:
    """Extract the best (max fitness) entry from a judger's output.

    judger_io is the per-node agent_io dict shape:
        {"input_prompt": ..., "system_prompt": ..., "output_result": <dict|str>}

    output_result is normally a dict (pydantic model_dump from node_factory
    success path) but may be a JSON string in edge cases. Returns None if
    output isn't shaped like a JudgerResult (no ranking array / empty).

    Returns: {best_fitness, best_strategy_id, best_latency_ms, best_metrics}
    """
    if not isinstance(judger_io, dict):
        return None
    output = judger_io.get("output_result")
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(output, dict):
        return None
    ranking = output.get("ranking")
    if not isinstance(ranking, list) or not ranking:
        return None
    try:
        best = max(
            ranking,
            key=lambda e: e.get("fitness", float("-inf")) if isinstance(e, dict) else float("-inf"),
        )
    except (TypeError, ValueError):
        return None
    if not isinstance(best, dict) or not isinstance(best.get("fitness"), (int, float)):
        return None
    return {
        "best_fitness": best.get("fitness"),
        "best_strategy_id": best.get("strategy_id"),
        "best_latency_ms": best.get("latency_ms"),
        "best_metrics": best.get("metrics") if isinstance(best.get("metrics"), dict) else None,
        "primary_metric": output.get("primary_metric"),
    }
