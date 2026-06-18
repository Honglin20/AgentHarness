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

        # Compute invocation counts from iter_index — agent_io only retains
        # the latest iter per node, but conversation messages need an
        # `iteration` field so the frontend's per-iter filtering works.
        # iter_index shape: {node_id: [{iter: 1, ...}, {iter: 2, ...}]}
        try:
            invocation_counts_raw = get_run_store().get_iter_index(wid) or {}
        except Exception:
            invocation_counts_raw = {}
        invocation_counts: dict[str, int] = {}
        # Loop var must not shadow the `node_id` parameter — that bug
        # silently re-targeted every per-iter sidecar write to whatever
        # the last iter_index key was.
        for idx_node, iter_entries in invocation_counts_raw.items():
            if not isinstance(iter_entries, list):
                continue
            iters = [e.get("iter") for e in iter_entries if isinstance(e, dict) and isinstance(e.get("iter"), int)]
            if iters:
                invocation_counts[idx_node] = max(iters)

        conversation_full = build_conversation(
            dict(builder.agent_io),
            invocation_counts=invocation_counts or None,
        )

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
            # D4: conversation is NOT passed — run_record no longer persists
            # it. The full conversation lives in per-iter sidecars (D2) and
            # the snapshot no longer embeds it either (D3 / P4). Old run
            # records retain their conversation field for read-only compat.
            chart_groups=chart_groups,
            created_at=data.get("created_at"),
            work_dir=data.get("work_dir"),
            todo_steps=todo_snapshot,
        )

        # Per-iter sidecar (Phase 2). Skip when caller didn't pass
        # invocation info (defensive — every callsite should pass it).
        if node_id is not None and iter_num is not None:
            iter_data = _build_iter_data(
                agent_io_snapshot=agent_io_snapshot,
                todo_states=builder.todo_states,
                node_id=node_id,
                iter_num=iter_num,
                duration_ms=duration_ms,
                status=status,
            )
            # R3 (ADR §R3): route sidecar write through save_iter_sidecar_safe —
            # atomic + verify + retry + log loud + don't raise. Index update
            # still goes through RunStore (separate small write, not
            # R3-protected yet — same atomic_write primitive though).
            try:
                from harness.persistence.sidecar_io import save_iter_sidecar_safe

                saved = save_iter_sidecar_safe(wid, node_id, iter_num, iter_data)
                if not saved:
                    logger.warning(
                        "Iter sidecar persistently failed for %s/%s/iter=%s — iter UI will miss this entry",
                        wid, node_id, iter_num,
                    )
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
        # agent_io already only retains the latest-iter io_data per node
        # (builder.agent_io[node] = io_data overwrites on each invocation),
        # so conversation_full is naturally the latest-iter view across all
        # agents. Historical iters load on demand from
        # /api/runs/{id}/conversation?node_id=X&iter_num=Y (per-iter sidecar).
        #
        # Previously we sliced conversation_full[-50:] to cap snapshot size,
        # but that truncated multi-agent workflows to just the trailing
        # agent's tool calls (NAS bug: refresh showed only `refiner` content
        # while outline listed all 9 agents). agent_io-driven build_conversation
        # is already iter-bounded, so no further slicing is needed.
        conversation_latest = conversation_full

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

        # Build latest_iter_by_node from iter_index. Replaces the old
        # nodes_latest shape ({node_id: {status, latest_iter}}) with the
        # ADR D3 manifest shape ({node_id: <int>}). Iter_index is the
        # authoritative source (D1) — deriving latest here avoids a
        # separate client-side computation.
        latest_iter_by_node: dict[str, int] = {}
        for nid, entries in iter_index.items():
            iters = [
                e.get("iter") for e in entries
                if isinstance(e, dict) and isinstance(e.get("iter"), int)
            ]
            if iters:
                latest_iter_by_node[nid] = max(iters)

        snapshot = {
            "version": 2,
            "run_id": wid,
            "workflow_name": data["workflow"].name,
            "status": "running",
            "created_at": data.get("created_at"),
            # D7 sync point: WS reconnect uses since_seq = snapshot.last_seq.
            # Renamed from seq_cursor (P4-T05).
            "last_seq": getattr(event_bus, "_seq", 0),
            "dag": dag,
            # D3 manifest fields — ADR D3 / D5:
            #   - conversation / agent_io / todo_states REMOVED from snapshot
            #     (Phase 4). They live in per-iter sidecars. Frontend
            #     hydrates by fetching sidecars on demand, never by reading
            #     these heavy fields from the manifest.
            #   - nodes_latest REMOVED → use latest_iter_by_node instead.
            #   - conversation_total REMOVED → pagination is per-sidecar.
            "latest_iter_by_node": latest_iter_by_node,
            "current_iter": current_iter,
            "iter_index": iter_index,
            # Phase 4: NAS fitness series. Each judger completion appends
            # one entry {iter, best_fitness, best_strategy_id, ...}. Empty
            # for non-NAS workflows or pre-judger setup phase.
            "fitness_history": fitness_history,
            # Charts stay in snapshot for now (chart sidecar is separate
            # but the snapshot points to it). P5+ may revisit.
            "charts": chart_groups,
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

        # Outline sidecar — same freshness contract as snapshot. Without this,
        # a NAS run that gets interrupted before final-save leaves the frontend
        # with no outline sidecar at all, so refresh falls back to deriving
        # from the (possibly partial) conversation and misses idle nodes.
        # Best-effort: failures are logged inside save_outline_sidecar.
        try:
            from harness.persistence.outline_save import save_outline_sidecar

            save_outline_sidecar(
                workflow_id=wid,
                conversation=conversation_full,
                events=list(event_bus.buffer) if event_bus else None,
                trace=[],
                todo_steps=todo_snapshot,
                agents_snapshot=data.get("agents_snapshot", []),
                dag=dag,
                iter_index=invocation_counts_raw,
            )
        except Exception:
            logger.warning(
                "Outline sidecar save failed for workflow %s — frontend will derive",
                wid,
                exc_info=True,
            )
    except Exception:
        logger.exception("Incremental save failed for workflow %s", wid)


def _build_iter_data(
    *,
    agent_io_snapshot: dict,
    todo_states: dict,
    node_id: str,
    iter_num: int,
    duration_ms: int | None,
    status: str,
) -> dict:
    """Construct the per-iter sidecar payload from builder state.

    Pure helper extracted from _save_incremental so the field projection
    (D2 content + O1 todo filtering) is unit-testable without mocking
    the full save pipeline.

    Args:
        agent_io_snapshot: builder.agent_io snapshot (node_id → io dict).
        todo_states: builder.todo_states (node_id → list of step dicts,
            each carrying an ``iteration`` field per O1).
        node_id, iter_num, duration_ms, status: identity + lifecycle.

    Returns:
        Dict shaped per ``schemas/iter_sidecar.v2.schema.json``. Always
        contains ``tool_calls`` (possibly []) and ``todo_steps`` (only
        the entries whose iteration == iter_num).
    """
    node_io = agent_io_snapshot.get(node_id) or {}
    output_result = node_io.get("output_result") if isinstance(node_io, dict) else None
    # D2: sidecar must carry tool_calls. tool_calls come straight from
    # agent_io[node] — they're already in memory, just weren't persisted.
    # Each call shape: {tool_name, tool_args, tool_result}
    node_tool_calls = (
        node_io.get("tool_calls")
        if isinstance(node_io, dict) and isinstance(node_io.get("tool_calls"), list)
        else []
    )
    # O1: per-iter todo steps. snapshot.todo_states[node] is a list of
    # {task_id, content, status, iteration, ...} across all iters. Filter
    # to just this iter. Steps missing iteration field are excluded — a
    # malformed step shouldn't pollute the sidecar.
    node_todo_all = todo_states.get(node_id)
    if not isinstance(node_todo_all, list):
        node_todo_all = []
    iter_todo_steps = [
        s for s in node_todo_all
        if isinstance(s, dict) and s.get("iteration") == iter_num
    ]
    return {
        "iter": iter_num,
        "node_id": node_id,
        "status": status,
        "duration_ms": duration_ms,
        "input_prompt": node_io.get("input_prompt") if isinstance(node_io, dict) else None,
        "system_prompt": node_io.get("system_prompt") if isinstance(node_io, dict) else None,
        "output": output_result,
        "tool_calls": node_tool_calls,
        "todo_steps": iter_todo_steps,
        # Short summary for iter dropdown — extract from common shapes.
        "summary": _extract_iter_summary(output_result),
        # Phase 3 fills events_seq_range by intersecting event seqs with
        # iter boundaries; for now, omit.
    }


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
