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


# Safety cap — see docstring. Above this, we collapse to latest-iter-per-node.
# 50 is roughly 5 cycle agents × 8 iters + setup nodes; legitimate runs stay
# well under this.
MAX_OUTLINE_ITEMS = 50


def compute_outline(
    *,
    conversation: list[dict] | None,
    events: list[dict] | None,
    trace: list[dict] | None,
    todo_steps: dict[str, list[dict]] | None,
    agents_snapshot: list[dict] | None,
    dag: dict | None,
    iter_index: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """Project raw run data into an OutlineItem-shaped summary list.

    See module docstring for the contract. Returns ``[]`` when there is not
    enough data to derive anything (caller writes no sidecar in that case).

    Iter metadata source (ADR D1): ``iter_index`` is the **single source of
    truth** for which (node, iter) pairs ran. Pre-P1 this came from scanning
    ``node.started`` events — but the bus replay buffer is FIFO and drops
    early events on long runs, so the scan was structurally unreliable.
    Now outline reads iter_index directly. When iter_index is absent or
    empty (legacy runs / setup-only runs), we fall back to synthesizing
    iter=1 per DAG node so idle nodes still render.

    Safety cap: if the run somehow produced more than ``MAX_ITEMS`` outline
    entries (e.g. a misbehaving cycle kept firing node.started), collapse
    each node to its latest iteration only. This prevents the 30k-item /
    multi-MB sidecar blowup observed during the 2026-06-17 cycle-loop
    incident, which made the frontend OOM on hydration.
    """
    conversation = conversation or []
    events = events or []
    trace = trace or []
    todo_steps = todo_steps or {}
    agents_snapshot = agents_snapshot or []
    dag_nodes: list[str] = list((dag or {}).get("nodes") or [])

    # In AgentHarness the DAG node id IS the agent's registered name (see
    # ``build_node_started_payload`` in node_phases.py — agent_name=node_id).
    # agents_snapshot entries are keyed by the same name, so the display name
    # is just the node id. Keep a snapshot set so unknown nodes still render.
    snapshot_names = {a.get("name") for a in agents_snapshot if a.get("name")}

    # trace lookup by agent_name (trace is agent-level, no iteration dim).
    # Two sources, merged:
    #   1. Explicit ``trace`` parameter (authoritative — WorkflowResult.trace
    #      from final-save). Used by server/runner.py final-save path.
    #   2. Fallback: synthesize from ``node.completed`` events when trace=[]
    #      (incremental_save path + failed-run path). Each node.completed
    #      event payload carries duration_ms + token_usage — same data the
    #      frontend's live deriveOutlineItems uses, so post-refresh badges
    #      match what the user saw pre-refresh.
    trace_by_agent: dict[str, dict] = {}
    for entry in trace:
        agent = entry.get("agent_name")
        if agent:
            trace_by_agent[agent] = entry

    # Fallback: extract trace from node.completed events. Walk in order so
    # the LATEST completion per node wins (matches outline's latest-iter
    # semantics). Only fills agents not already in trace_by_agent — the
    # explicit trace param stays authoritative when both sources have data.
    if events:
        for ev in events:
            if ev.get("type") != "node.completed":
                continue
            payload = ev.get("payload") or {}
            node_id = payload.get("node_id") or payload.get("agent_name")
            if not node_id or node_id in trace_by_agent:
                continue
            entry: dict = {"agent_name": node_id}
            if payload.get("duration_ms") is not None:
                entry["duration_ms"] = payload.get("duration_ms")
            if payload.get("token_usage") is not None:
                entry["token_usage"] = payload.get("token_usage")
            if payload.get("status"):
                entry["status"] = payload.get("status")
            if len(entry) > 1:  # has more than just agent_name
                trace_by_agent[node_id] = entry

    # 1. Collect (nodeId, iteration) pairs from iter_index (ADR D1).
    #    iter_index shape: {node_id: [{iter: int, started_at: ts, ...}, ...]}.
    #    node.started events are NO LONGER scanned for iter discovery —
    #    the event buffer is FIFO and drops early events on long runs, so
    #    the events-based path was structurally broken (see ADR §问题量化).
    #    Events are still used below for status/retry detection.
    iter_set: dict[str, dict] = {}
    for node_id, entries in (iter_index or {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            iter_num = entry.get("iter")
            if not isinstance(iter_num, int) or iter_num < 1:
                continue
            key = f"{node_id}__iter{iter_num}"
            if key in iter_set:
                continue
            started = entry.get("started_at")
            iter_set[key] = {
                "node_id": node_id,
                "iteration": iter_num,
                # Prefer started_at from iter_index; msg_first_ts refines below.
                "first_ts": started if isinstance(started, (int, float)) else float("inf"),
            }

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
        if not node_id or _is_followup_node(node_id):
            continue
        ts = m.get("timestamp") or m.get("ts") or 0
        if node_id not in msg_first_ts_by_node or ts < msg_first_ts_by_node[node_id]:
            msg_first_ts_by_node[node_id] = ts

    # 3. Fallback: no iter_index (legacy / setup-only run) — synthesize
    #    iter=1 for every DAG node so the outline is non-empty. Without
    #    this, refresh on an old run shows no outline at all. iter_index
    #    becomes authoritative once the run emits its first cycle iter.
    if not iter_set:
        for node_id in dag_nodes:
            key = f"{node_id}__iter1"
            iter_set[key] = {
                "node_id": node_id,
                "iteration": 1,
                "first_ts": msg_first_ts_by_node.get(node_id) or float("inf"),
            }

    # 3b. Idle DAG nodes (no entry in iter_index at all) — synthesize iter=1
    #     so they still render in the outline. Mirrors deriveOutlineItems.ts:57-62.
    nodes_in_index = {entry["node_id"] for entry in iter_set.values()}
    for node_id in dag_nodes:
        if node_id in nodes_in_index:
            continue
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
        if not node_id or _is_followup_node(node_id):
            continue
        if m_type == "question" and m_status == "pending":
            pending_q_by_node[node_id] = pending_q_by_node.get(node_id, 0) + 1

    # 8. Per-(nodeId, iter) message status scan for historical iters'
    #    status inference (mirror deriveOutlineItems.ts:151-160). Backend
    #    messages lack iteration so this is approximate for non-latest iters.
    msg_status_by_node: dict[str, list[str]] = {}
    for m in conversation:
        node_id = m.get("nodeId") or m.get("node_id")
        if not node_id or _is_followup_node(node_id):
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

    # 9b. Latest retry attempt per node. ``agent.retry_attempted`` carries
    #     ``attempt`` (the attempt that JUST FAILED, 1-indexed) + ``max_attempts``
    #     (mirrors NodeState.retryAttempts on the frontend). UI shows attempt+1
    #     = the upcoming attempt number (matches deriveOutlineItems.ts:181-188).
    latest_retry_by_node: dict[str, dict] = {}
    for ev in events:
        if ev.get("type") != "agent.retry_attempted":
            continue
        payload = ev.get("payload") or {}
        node_id = payload.get("node_id")
        if not node_id:
            continue
        latest_retry_by_node[node_id] = {
            "attempt": int(payload.get("attempt") or 1),
            "max_attempts": int(payload.get("max_attempts") or 1),
        }

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
        # AgentHarness: agent_name == node_id (see node_phases.build_node_started_payload).
        # Display name = node id; snapshot presence is just a sanity guard.
        name = node_id if node_id in snapshot_names or not snapshot_names else node_id
        node_trace = trace_by_agent.get(node_id, {})
        node_status_event = latest_event_status_by_node.get(node_id)
        pending_q = pending_q_by_node.get(node_id, 0)
        statuses_for_node = msg_status_by_node.get(node_id, [])
        retry_info = latest_retry_by_node.get(node_id)

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
            retry_info=retry_info,
        )
        badges = _compute_badges(
            iteration=iteration,
            iter_count=iter_count,
            is_latest_iter=is_latest_iter,
            node_trace=node_trace,
            retry_info=retry_info,
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

    return _cap_items(items)


def _cap_items(items: list[dict]) -> list[dict]:
    """Collapse oversized outlines to latest-iter-per-node.

    When a cycle misbehaves (the 2026-06-17 incident produced 29999 items),
    rendering that many OutlineItemRow components freezes the browser.
    Keep only the highest-iteration item per node — that's the only one the
    UI surfaces in the latest-state view anyway. Historical iters remain
    queryable via the per-iter sidecars.
    """
    if len(items) <= MAX_OUTLINE_ITEMS:
        return items
    latest_per_node: dict[str, dict] = {}
    for item in items:
        node_id = item["node_id"]
        prev = latest_per_node.get(node_id)
        if prev is None or item["iteration"] > prev["iteration"]:
            latest_per_node[node_id] = item
    # Re-sort + re-index order to keep display stable.
    collapsed = sorted(
        latest_per_node.values(),
        key=lambda it: (it["first_ts"], it["order"], it["iteration"]),
    )
    for new_order, item in enumerate(collapsed):
        item["order"] = new_order
    return collapsed


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
    retry_info: dict | None,
) -> dict:
    """Mirror ``computeActivity`` in deriveOutlineItems.ts:163-211."""
    if pending_q > 0:
        return {"kind": "waiting-for-user", "questionId": "", "questionCount": pending_q}
    if not is_latest_iter:
        return {"kind": "completed"}
    if node_status_event == "retrying" and retry_info:
        # Mirror frontend: display attempt+1 (the upcoming attempt) — matches
        # the toast at agentHandlers and the inline retry card at AgentMessage.
        return {
            "kind": "retrying",
            "attempt": retry_info["attempt"] + 1,
            "maxAttempts": retry_info["max_attempts"],
        }
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
    retry_info: dict | None,
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
        # Retry badge first (matches frontend ordering: retry → tokens).
        # Display upcoming attempt (attempt+1); same convention as activity.
        if retry_info:
            upcoming = retry_info["attempt"] + 1
            max_attempts = retry_info["max_attempts"]
            badges.append({
                "kind": "retry",
                "text": f"{upcoming}/{max_attempts}",
                "title": f"Retry attempt {upcoming} of {max_attempts}",
            })
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


def _is_followup_node(node_id: str) -> bool:
    """Synthetic @mention followup nodeIds start with ``followup-``.

    ChatInput creates these for multi-turn @agent conversations; they never
    fire node.started, so they're not real DAG nodes. deriveOutlineItems.ts:45
    skips them in the message scan — we do the same so followup messages
    don't pollute first_ts / pending_question / status maps.
    """
    return node_id.startswith("followup-")
