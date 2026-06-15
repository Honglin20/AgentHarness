"""Compute the outline summary sidecar from raw run data.

Mirrors the algorithm in ``frontend/src/components/outline/deriveOutlineItems.ts``
so the replay-mode outline rendered from the sidecar matches what live mode
derives from the full conversation. Any divergence would surface as a visible
"outline changed after switching to history" flicker.

Inputs are the raw facts already available at the final-save call site
(``server/runner.py``): conversation messages, the bus events buffer, the
result trace, persisted todo steps, agents snapshot, and the DAG. The output
is a list of dicts shaped like the frontend ``OutlineItem`` interface.

This module is pure — no I/O, no globals. Failures bubble up as exceptions;
the caller (``server/runner.py``) wraps the call in try/except so a buggy
projection never blocks the main run-record save.
"""
from __future__ import annotations

from typing import Any


def compute_outline(
    *,
    conversation: list[dict] | None,
    events: list[dict] | None,
    trace: list[dict] | None,
    todo_steps: dict[str, list[dict]] | None,
    agents_snapshot: list[dict] | None,
    dag: dict | None,
) -> list[dict]:
    """Project raw run data into an OutlineItem-shaped summary list.

    See module docstring for the contract. Returns ``[]`` when there is not
    enough data to derive anything (caller writes no sidecar in that case).
    """
    conversation = conversation or []
    events = events or []
    trace = trace or []
    todo_steps = todo_steps or {}
    agents_snapshot = agents_snapshot or []
    dag_nodes: list[str] = list((dag or {}).get("nodes") or [])

    # agent_name lookup from snapshot — frontend uses NodeState.name which is
    # populated by the workflow store from the same snapshot.
    name_by_node = {a.get("name"): a.get("name") for a in agents_snapshot}
    # Snapshot name is the node id; the display name is whatever the agent
    # registered as. For now there is no separate display-name field, so
    # fall back to node id.
    for node_id in dag_nodes:
        name_by_node.setdefault(node_id, node_id)

    # trace lookup by agent_name (trace is agent-level, no iteration dim)
    trace_by_agent: dict[str, dict] = {}
    for entry in trace:
        agent = entry.get("agent_name")
        if agent:
            trace_by_agent[agent] = entry

    # 1. Collect (nodeId, iteration) pairs from node.started events.
    #    These are the source of truth for "which iterations ran" — bus
    #    emits one node.started per invocation with the iteration counter.
    iter_set: dict[str, dict] = {}
    started_ts: dict[str, int] = {}
    for ev in events:
        if ev.get("type") != "node.started":
            continue
        payload = ev.get("payload") or {}
        node_id = payload.get("node_id")
        if not node_id:
            continue
        iteration = int(payload.get("iteration") or 1)
        key = f"{node_id}__iter{iteration}"
        ts = payload.get("ts") or ev.get("ts") or 0
        if key not in iter_set:
            iter_set[key] = {
                "node_id": node_id,
                "iteration": iteration,
                "first_ts": ts,
            }
            started_ts[key] = ts
        else:
            # Keep earliest ts for stable sort.
            if ts < iter_set[key]["first_ts"]:
                iter_set[key]["first_ts"] = ts
                started_ts[key] = ts

    # 2. Refine first_ts from conversation messages (sub-event granularity).
    #    node.started fires before any agent output; the conversation's first
    #    message for this (nodeId, iter) is closer to "user-visible activity".
    #    Backward compat: backend conversation message has no iteration field,
    #    so we attribute all messages for a node to its latest iteration. This
    #    over-attributes but only affects first_ts of historical iters, which
    #    are not user-visible (the latest iter is what the outline emphasizes).
    msg_first_ts_by_node: dict[str, int] = {}
    for m in conversation:
        node_id = m.get("nodeId") or m.get("node_id")
        if not node_id:
            continue
        ts = m.get("timestamp") or m.get("ts") or 0
        if node_id not in msg_first_ts_by_node or ts < msg_first_ts_by_node[node_id]:
            msg_first_ts_by_node[node_id] = ts

    # 3. Idle nodes (no node.started, no messages) — synthesize iter=1 entry
    #    so they show up in the outline. Mirrors deriveOutlineItems.ts:57-62.
    for node_id in dag_nodes:
        key = f"{node_id}__iter1"
        if key not in iter_set:
            iter_set[key] = {
                "node_id": node_id,
                "iteration": 1,
                "first_ts": msg_first_ts_by_node.get(node_id) or float("inf"),
            }

    # 4. Count iterations per node for the badge + is_latest_iter flag.
    iter_count_by_node: dict[str, int] = {}
    for entry in iter_set.values():
        node_id = entry["node_id"]
        iter_count_by_node[node_id] = iter_count_by_node.get(node_id, 0) + 1

    # 5. DAG declaration order — stable secondary sort key for idle nodes.
    node_dag_order = {node_id: idx for idx, node_id in enumerate(dag_nodes)}

    # 6. Sort: first_ts asc, then DAG order, then iteration. Matches
    #    deriveOutlineItems.ts:73-79.
    sorted_entries = sorted(
        iter_set.values(),
        key=lambda e: (
            e["first_ts"],
            node_dag_order.get(e["node_id"], float("inf")),
            e["iteration"],
        ),
    )

    # 7. Pending questions per (nodeId, iter) from conversation. Backend
    #    messages lack iteration, so attribute to latest iter — same caveat
    #    as msg_first_ts. Pending questions are inherently "latest state"
    #    anyway (an unanswered question blocks the iter from completing).
    pending_q_by_node: dict[str, int] = {}
    for m in conversation:
        m_type = m.get("type") or m.get("kind")
        m_status = m.get("status")
        node_id = m.get("nodeId") or m.get("node_id")
        if m_type == "question" and m_status == "pending" and node_id:
            pending_q_by_node[node_id] = pending_q_by_node.get(node_id, 0) + 1

    # 8. Per-(nodeId, iter) message status scan for historical iters'
    #    status inference (mirror deriveOutlineItems.ts:151-160). Backend
    #    messages lack iteration so this is approximate for non-latest iters.
    msg_status_by_node: dict[str, list[str]] = {}
    for m in conversation:
        node_id = m.get("nodeId") or m.get("node_id")
        if not node_id:
            continue
        m_status = m.get("status")
        if m_status:
            msg_status_by_node.setdefault(node_id, []).append(m_status)

    # 9. Latest event status per node (running | success | failed | retrying).
    #    Walk events in order; the last node.started/completed/failed wins.
    latest_event_status_by_node: dict[str, str] = {}
    for ev in events:
        etype = ev.get("type")
        if etype not in ("node.started", "node.completed", "node.failed"):
            continue
        payload = ev.get("payload") or {}
        node_id = payload.get("node_id")
        if not node_id:
            continue
        if etype == "node.started":
            latest_event_status_by_node[node_id] = "running"
        elif etype == "node.completed":
            latest_event_status_by_node[node_id] = payload.get("status") or "success"
        elif etype == "node.failed":
            will_retry = payload.get("will_retry")
            latest_event_status_by_node[node_id] = "retrying" if will_retry else "failed"

    # 10. Active step per node (in_progress todo) — mirror deriveOutlineItems.ts:200-205.
    active_step_by_node: dict[str, dict] = {}
    for node_id, steps in todo_steps.items():
        for step in steps:
            if step.get("status") == "in_progress":
                active_step_by_node[node_id] = {
                    "content": step.get("content"),
                    "activeForm": step.get("activeForm"),
                }
                break

    # 11. Build OutlineItem-shaped dict per entry.
    items: list[dict] = []
    for order, entry in enumerate(sorted_entries):
        node_id = entry["node_id"]
        iteration = entry["iteration"]
        iter_count = iter_count_by_node.get(node_id, 1)
        is_latest_iter = iteration == iter_count
        name = name_by_node.get(node_id, node_id)
        node_trace = trace_by_agent.get(node_id, {})
        node_status_event = latest_event_status_by_node.get(node_id)
        pending_q = pending_q_by_node.get(node_id, 0)
        statuses_for_node = msg_status_by_node.get(node_id, [])

        status = _compute_status(
            is_latest_iter=is_latest_iter,
            pending_q=pending_q,
            node_status_event=node_status_event,
            msg_statuses=statuses_for_node,
            has_trace=bool(node_trace),
        )
        activity = _compute_activity(
            is_latest_iter=is_latest_iter,
            pending_q=pending_q,
            node_status_event=node_status_event,
            node_trace=node_trace,
            active_step=active_step_by_node.get(node_id),
        )
        badges = _compute_badges(
            iteration=iteration,
            iter_count=iter_count,
            is_latest_iter=is_latest_iter,
            node_trace=node_trace,
        )

        first_ts = entry["first_ts"]
        items.append({
            "key": f"{node_id}__iter{iteration}",
            "node_id": node_id,
            "iteration": iteration,
            "is_latest_iter": is_latest_iter,
            "iter_count": iter_count,
            "name": name,
            # JSON cannot serialize float('inf'); coerce idle placeholders to 0
            # so the field is always a valid number. Sort order is already
            # captured in `order`.
            "first_ts": first_ts if isinstance(first_ts, (int, float)) and first_ts != float("inf") else 0,
            "status": status,
            "activity": activity,
            "badges": badges,
            "order": order,
        })

    return items


# ---------------------------------------------------------------------------
# Mirrored helpers — keep semantics aligned with deriveOutlineItems.ts
# ---------------------------------------------------------------------------

def _compute_status(
    *,
    is_latest_iter: bool,
    pending_q: int,
    node_status_event: str | None,
    msg_statuses: list[str],
    has_trace: bool,
) -> str:
    """Mirror ``computeStatus`` in deriveOutlineItems.ts:131-161."""
    if is_latest_iter:
        if pending_q > 0:
            return "waiting-for-user"
        if node_status_event == "running":
            return "running"
        if node_status_event == "failed":
            return "failed"
        if node_status_event == "retrying":
            return "retrying"
        if node_status_event in ("success", "completed"):
            return "completed"
        return "idle"
    # Historical iter — derive from message statuses.
    if any(s in ("error", "interrupted") for s in msg_statuses):
        return "failed"
    if any(s == "done" for s in msg_statuses):
        return "completed"
    if has_trace:
        return "completed"
    return "idle"


def _compute_activity(
    *,
    is_latest_iter: bool,
    pending_q: int,
    node_status_event: str | None,
    node_trace: dict,
    active_step: dict | None,
) -> dict:
    """Mirror ``computeActivity`` in deriveOutlineItems.ts:163-211."""
    if pending_q > 0:
        return {"kind": "waiting-for-user", "questionId": "", "questionCount": pending_q}
    if not is_latest_iter:
        return {"kind": "completed"}
    if node_status_event == "failed":
        error_summary = node_trace.get("error") or "Failed"
        return {"kind": "failed", "errorSummary": str(error_summary)}
    if node_status_event == "running":
        return {
            "kind": "running",
            "currentStepContent": (active_step or {}).get("activeForm")
            or (active_step or {}).get("content"),
        }
    if node_status_event in ("success", "completed"):
        duration_ms = node_trace.get("duration_ms")
        return {
            "kind": "completed",
            **({"durationMs": duration_ms} if duration_ms is not None else {}),
        }
    return {"kind": "idle"}


def _compute_badges(
    *,
    iteration: int,
    iter_count: int,
    is_latest_iter: bool,
    node_trace: dict,
) -> list[dict]:
    """Mirror ``computeBadges`` in deriveOutlineItems.ts:213-249."""
    badges: list[dict] = []
    if iter_count > 1:
        badges.append({
            "kind": "iteration",
            "text": f"#{iteration}",
            "title": f"Iteration {iteration} of {iter_count}",
        })
    if is_latest_iter:
        token_usage = node_trace.get("token_usage") or {}
        total = token_usage.get("total") if isinstance(token_usage, dict) else None
        if total and total > 0:
            badges.append({
                "kind": "tokens",
                "text": _format_tokens(total),
                "title": f"{token_usage.get('input', 0)} in / {token_usage.get('output', 0)} out",
            })
    return badges


def _format_tokens(n: int) -> str:
    """Mirror ``formatTokens`` in deriveOutlineItems.ts:251-254."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)
