"""Unit tests for harness.persistence.outline_compute.compute_outline.

Validates the projection mirrors the frontend deriveOutlineItems algorithm.
Each test case exercises a distinct branch of the computation: single iter,
multi iter, idle nodes, failed status, pending questions, retry, running
active step.

ADR D1 (post-P1): iter_index is the single source of truth for iter
discovery. Tests that previously relied on events to populate iter_set now
construct iter_index directly. Events are still used for status detection
(running / failed / retrying) — that path is unchanged.
"""
from harness.persistence.outline_compute import compute_outline


def _started(node_id, iteration=1, ts=1000):
    return {
        "type": "node.started",
        "ts": ts,
        "payload": {"node_id": node_id, "iteration": iteration, "ts": ts, "agent_name": node_id},
    }


def _completed(node_id, status="success", duration_ms=500, token_usage=None, ts=2000):
    payload = {"node_id": node_id, "agent_name": node_id, "duration_ms": duration_ms, "status": status, "ts": ts}
    if token_usage:
        payload["token_usage"] = token_usage
    return {"type": "node.completed", "ts": ts, "payload": payload}


def _failed(node_id, will_retry=False, ts=2000):
    return {
        "type": "node.failed",
        "ts": ts,
        "payload": {
            "node_id": node_id,
            "agent_name": node_id,
            "error": "boom",
            "duration_ms": 100,
            "will_retry": will_retry,
            "ts": ts,
        },
    }


def _msg(node_id, status, ts, m_type="agent"):
    return {"nodeId": node_id, "status": status, "timestamp": ts, "type": m_type}


def _iter_index(node_id, iters):
    """Build an iter_index entry: {node_id: [{iter: 1, ...}, ...]}.

    iters can be a list of int (iter numbers) or a list of dicts (full entries).
    """
    entries = []
    for it in iters:
        if isinstance(it, dict):
            entries.append(it)
        else:
            entries.append({"iter": it, "status": "completed", "summary": f"iter {it}"})
    return {node_id: entries}


def test_single_iter_completed():
    dag = {"nodes": ["scout"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[_started("scout", ts=1000), _completed("scout", duration_ms=2000, token_usage={"input": 100, "output": 50, "total": 150})],
        trace=[{"agent_name": "scout", "status": "success", "duration_ms": 2000, "token_usage": {"input": 100, "output": 50, "total": 150}}],
        todo_steps={},
        agents_snapshot=[{"name": "scout"}],
        dag=dag,
        iter_index=_iter_index("scout", [1]),
    )
    assert len(out) == 1
    item = out[0]
    assert item["node_id"] == "scout"
    assert item["iteration"] == 1
    assert item["iter_count"] == 1
    assert item["is_latest_iter"] is True
    assert item["status"] == "completed"
    assert item["activity"] == {"kind": "completed", "durationMs": 2000}
    # token badge present on latest iter when total > 0
    assert any(b["kind"] == "tokens" and b["text"] == "150" for b in item["badges"])


def test_multi_iter_emits_one_entry_per_iter():
    dag = {"nodes": ["trainer"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[
            _started("trainer", iteration=1, ts=1000),
            _completed("trainer", ts=2000),
            _started("trainer", iteration=2, ts=3000),
            _completed("trainer", ts=4000),
            _started("trainer", iteration=3, ts=5000),
            _completed("trainer", ts=6000),
        ],
        trace=[{"agent_name": "trainer", "status": "success", "duration_ms": 6000}],
        todo_steps={},
        agents_snapshot=[{"name": "trainer"}],
        dag=dag,
        iter_index=_iter_index("trainer", [1, 2, 3]),
    )
    assert len(out) == 3
    assert [it["iteration"] for it in out] == [1, 2, 3]
    assert all(it["iter_count"] == 3 for it in out)
    assert out[0]["is_latest_iter"] is False
    assert out[1]["is_latest_iter"] is False
    assert out[2]["is_latest_iter"] is True
    # Iter badge appears on all rows when iter_count > 1
    assert all(any(b["kind"] == "iteration" for b in it["badges"]) for it in out)
    assert out[2]["badges"][0] == {"kind": "iteration", "text": "#3", "title": "Iteration 3 of 3"}


def test_idle_nodes_synthesized_iter1():
    """No iter_index entries + nodes in DAG → idle iter=1 entries.

    P1-T03 fallback path: legacy runs / setup-only runs have no iter_index,
    so every DAG node synthesizes an iter=1 entry to keep outline non-empty.
    """
    dag = {"nodes": ["scout", "planner"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "scout"}, {"name": "planner"}],
        dag=dag,
        iter_index=None,
    )
    assert len(out) == 2
    assert all(it["status"] == "idle" for it in out)
    assert all(it["activity"] == {"kind": "idle"} for it in out)
    assert all(it["is_latest_iter"] is True for it in out)
    # first_ts coerced to 0 for idle (no JSON inf)
    assert all(it["first_ts"] == 0 for it in out)


def test_failed_node_status():
    dag = {"nodes": ["trainer"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[_started("trainer", ts=1000), _failed("trainer", will_retry=False)],
        trace=[{"agent_name": "trainer", "status": "failed", "error": "OOM"}],
        todo_steps={},
        agents_snapshot=[{"name": "trainer"}],
        dag=dag,
        iter_index=_iter_index("trainer", [1]),
    )
    assert out[0]["status"] == "failed"
    assert out[0]["activity"] == {"kind": "failed", "errorSummary": "OOM"}


def test_retrying_status_when_will_retry():
    dag = {"nodes": ["trainer"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[_started("trainer", ts=1000), _failed("trainer", will_retry=True)],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "trainer"}],
        dag=dag,
        iter_index=_iter_index("trainer", [1]),
    )
    assert out[0]["status"] == "retrying"


def test_running_node_with_active_step():
    dag = {"nodes": ["trainer"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[_started("trainer", ts=1000)],  # no completed yet
        trace=[],
        todo_steps={"trainer": [{"content": "train model", "activeForm": "training", "status": "in_progress"}]},
        agents_snapshot=[{"name": "trainer"}],
        dag=dag,
        iter_index=_iter_index("trainer", [1]),
    )
    assert out[0]["status"] == "running"
    assert out[0]["activity"] == {"kind": "running", "currentStepContent": "training"}


def test_pending_question_blocks_node():
    dag = {"nodes": ["scout"], "edges": []}
    out = compute_outline(
        conversation=[
            {"type": "question", "status": "pending", "nodeId": "scout", "timestamp": 1500},
        ],
        events=[_started("scout", ts=1000)],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "scout"}],
        dag=dag,
        iter_index=_iter_index("scout", [1]),
    )
    assert out[0]["status"] == "waiting-for-user"
    assert out[0]["activity"] == {"kind": "waiting-for-user", "questionId": "", "questionCount": 1}


def test_retrying_emits_activity_and_badge():
    """Retry status must mirror deriveOutlineItems.ts:181-188 + 229-239.

    agent.retry_attempted payload carries attempt (the one that JUST FAILED,
    1-indexed) + max_attempts. UI shows attempt+1 = the upcoming attempt.
    """
    dag = {"nodes": ["trainer"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[
            _started("trainer", ts=1000),
            _failed("trainer", will_retry=True),
            {
                "type": "agent.retry_attempted",
                "ts": 2500,
                "payload": {
                    "node_id": "trainer",
                    "agent_name": "trainer",
                    "attempt": 1,
                    "max_attempts": 3,
                },
            },
        ],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "trainer"}],
        dag=dag,
        iter_index=_iter_index("trainer", [1]),
    )
    item = out[0]
    assert item["status"] == "retrying"
    assert item["activity"] == {"kind": "retrying", "attempt": 2, "maxAttempts": 3}
    # Retry badge should be present, showing upcoming attempt 2/3.
    retry_badges = [b for b in item["badges"] if b["kind"] == "retry"]
    assert len(retry_badges) == 1
    assert retry_badges[0] == {
        "kind": "retry",
        "text": "2/3",
        "title": "Retry attempt 2 of 3",
    }


def test_followup_messages_excluded_from_projections():
    """@mention followup nodeIds (`followup-<agent>`) must not pollute the
    outline maps. They never fire node.started, so they shouldn't appear as
    phantom outline rows or skew first_ts / pending_q of real DAG nodes.
    """
    dag = {"nodes": ["scout"], "edges": []}
    out = compute_outline(
        conversation=[
            # Real scout message at ts=2000
            {"type": "agent", "status": "done", "nodeId": "scout", "timestamp": 2000},
            # followup- noise: earlier ts (would skew scout first_ts) + pending question
            {"type": "agent", "status": "done", "nodeId": "followup-trainer", "timestamp": 500},
            {"type": "question", "status": "pending", "nodeId": "followup-trainer", "timestamp": 600},
        ],
        events=[_started("scout", ts=1000), _completed("scout", ts=3000)],
        trace=[{"agent_name": "scout", "status": "success", "duration_ms": 2000}],
        todo_steps={},
        agents_snapshot=[{"name": "scout"}],
        dag=dag,
        iter_index=_iter_index("scout", [1]),
    )
    # Only scout appears — followup-trainer is not in DAG and its messages
    # don't pollute scout's first_ts or pending_q.
    assert len(out) == 1
    assert out[0]["node_id"] == "scout"
    assert out[0]["status"] == "completed"
    # first_ts not skewed by followup ts=500 (would have been 500 if not filtered).
    assert out[0]["first_ts"] != 500


def test_sort_by_first_ts_then_dag_order():
    """Out-of-order events should still produce DAG-ordered idle tail."""
    dag = {"nodes": ["a", "b", "c"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[_started("c", ts=1000), _completed("c", ts=1100)],
        trace=[{"agent_name": "c", "status": "success", "duration_ms": 100}],
        todo_steps={},
        agents_snapshot=[{"name": "a"}, {"name": "b"}, {"name": "c"}],
        dag=dag,
        iter_index={"c": [{"iter": 1, "started_at": 1000}]},
    )
    # c ran first (earliest started_at), a/b idle in DAG order
    assert [it["node_id"] for it in out] == ["c", "a", "b"]


def test_empty_inputs_returns_empty_list():
    out = compute_outline(
        conversation=None,
        events=None,
        trace=None,
        todo_steps=None,
        agents_snapshot=None,
        dag=None,
        iter_index=None,
    )
    assert out == []


def test_order_field_is_sequence_index():
    """order is 0-indexed sequence in sorted output — frontend uses it as a stable key."""
    dag = {"nodes": ["a", "b", "c"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "a"}, {"name": "b"}, {"name": "c"}],
        dag=dag,
        iter_index=None,
    )
    assert [it["order"] for it in out] == [0, 1, 2]


# ── Safety cap: oversized outline collapses to latest-iter-per-node ────


def test_outline_under_cap_not_truncated():
    """Below MAX_OUTLINE_ITEMS (50), every iter stays in the output."""
    dag = {"nodes": [f"n{i}" for i in range(10)], "edges": []}
    # 10 nodes × 1 iter each = 10 outline items — under cap.
    iter_index = {f"n{i}": [{"iter": 1}] for i in range(10)}
    out = compute_outline(
        conversation=[],
        events=[],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": f"n{i}"} for i in range(10)],
        dag=dag,
        iter_index=iter_index,
    )
    assert len(out) == 10


def test_outline_over_cap_collapses_to_latest_iter_per_node():
    """When items > MAX_OUTLINE_ITEMS, keep only the highest-iter item per node.

    Regression: the 2026-06-17 cycle-loop incident produced 29999 outline
    items (5000 cycle iterations × 6 cycle agents), which froze the browser
    on hydration. The cap collapses this to one entry per node so the
    outline sidecar stays bounded."""
    # 1 node, 100 iterations — would normally produce 100 outline items.
    dag = {"nodes": ["validator"], "edges": []}
    iter_index = _iter_index("validator", list(range(1, 101)))
    out = compute_outline(
        conversation=[],
        events=[],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "validator"}],
        dag=dag,
        iter_index=iter_index,
    )
    # Collapsed to a single item — the highest-iter one.
    assert len(out) == 1
    assert out[0]["node_id"] == "validator"
    assert out[0]["iteration"] == 100
    # order field re-indexed after collapse so the frontend renders cleanly
    assert out[0]["order"] == 0


def test_outline_cap_preserves_multi_node_distinction():
    """Even after collapse, distinct nodes remain distinct items.

    A 5000-iter runaway on one node shouldn't merge with another node's
    single iter — the cap is per-node, not global."""
    dag = {"nodes": ["selector", "validator"], "edges": []}
    iter_index = {
        "selector": [{"iter": i} for i in range(1, 60)],
        "validator": [{"iter": 1}],
    }
    out = compute_outline(
        conversation=[],
        events=[],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "selector"}, {"name": "validator"}],
        dag=dag,
        iter_index=iter_index,
    )
    assert len(out) == 2
    node_ids = {it["node_id"] for it in out}
    assert node_ids == {"selector", "validator"}
    # selector kept its latest (59th) iter; validator kept its only (1st).
    sel = next(it for it in out if it["node_id"] == "selector")
    val = next(it for it in out if it["node_id"] == "validator")
    assert sel["iteration"] == 59
    assert val["iteration"] == 1


# ── P1-T07 / P1-T08: iter_index-driven + legacy fallback ────────────────


def test_outline_with_multi_iter_index():
    """ADR D1: iter_index is the source of truth for iter discovery.

    Construct an iter_index with 3 scout iters; outline must emit 3 scout
    entries with iter_count=3, regardless of events buffer state.
    """
    dag = {"nodes": ["scout"], "edges": []}
    iter_index = {
        "scout": [
            {"iter": 1, "status": "completed", "summary": "iter 1", "started_at": 1000},
            {"iter": 2, "status": "completed", "summary": "iter 2", "started_at": 2000},
            {"iter": 3, "status": "completed", "summary": "iter 3", "started_at": 3000},
        ]
    }
    out = compute_outline(
        conversation=[],
        events=[],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "scout"}],
        dag=dag,
        iter_index=iter_index,
    )
    assert len(out) == 3
    assert [it["iteration"] for it in out] == [1, 2, 3]
    assert all(it["iter_count"] == 3 for it in out)
    assert all(it["node_id"] == "scout" for it in out)
    # started_at from iter_index flows through to first_ts (refined later by
    # conversation, which is empty here).
    assert out[0]["first_ts"] == 1000
    assert out[1]["first_ts"] == 2000
    assert out[2]["first_ts"] == 3000


def test_outline_fallback_no_iter_index():
    """P1-T03: iter_index=None → synthesize iter=1 for every DAG node."""
    dag = {"nodes": ["a", "b", "c"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "a"}, {"name": "b"}, {"name": "c"}],
        dag=dag,
        iter_index=None,
    )
    assert len(out) == 3
    assert all(it["iteration"] == 1 for it in out)
    assert all(it["iter_count"] == 1 for it in out)
    assert {it["node_id"] for it in out} == {"a", "b", "c"}


def test_outline_fallback_empty_iter_index():
    """P1-T03: iter_index={} (empty dict) → same fallback as None."""
    dag = {"nodes": ["a", "b"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[],
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "a"}, {"name": "b"}],
        dag=dag,
        iter_index={},
    )
    assert len(out) == 2
    assert all(it["iteration"] == 1 for it in out)


# ── Token / duration badge recovery (regression for refresh-loses-badges bug) ──


def test_outline_recovers_token_duration_from_events_when_trace_empty():
    """Regression: incremental_save passes trace=[] to save_outline_sidecar.
    Before this fix, refresh wiped token/duration badges because trace_by_agent
    was empty. Now compute_outline synthesizes trace from node.completed events
    (same data source as the frontend's live deriveOutlineItems).
    """
    dag = {"nodes": ["scout"], "edges": []}
    completed_event = {
        "type": "node.completed",
        "seq": 10,
        "ts": 2000,
        "payload": {
            "node_id": "scout",
            "agent_name": "scout",
            "duration_ms": 5555,
            "status": "success",
            "token_usage": {"input": 1000, "output": 500, "total": 1500},
        },
    }
    out = compute_outline(
        conversation=[],
        events=[completed_event],
        trace=[],  # ← simulates _save_incremental's call
        todo_steps={},
        agents_snapshot=[{"name": "scout"}],
        dag=dag,
        iter_index={"scout": [{"iter": 1, "started_at": 1000}]},
    )
    assert len(out) == 1
    item = out[0]
    # Token badge must be present (regression check).
    token_badges = [b for b in item["badges"] if b["kind"] == "tokens"]
    assert len(token_badges) == 1
    assert token_badges[0]["text"] == "1.5k"
    # Duration must be in activity (regression check).
    assert item["activity"]["kind"] == "completed"
    assert item["activity"]["durationMs"] == 5555


def test_outline_explicit_trace_takes_precedence_over_events_trace():
    """When both explicit trace AND events-derived trace exist for a node,
    the explicit trace wins (it's the authoritative final-save source)."""
    dag = {"nodes": ["scout"], "edges": []}
    completed_event = {
        "type": "node.completed",
        "seq": 10,
        "ts": 2000,
        "payload": {
            "node_id": "scout",
            "agent_name": "scout",
            "duration_ms": 9999,  # events-derived value
            "status": "success",
            "token_usage": {"input": 1, "output": 1, "total": 2},
        },
    }
    explicit_trace = [{
        "agent_name": "scout",
        "duration_ms": 1111,  # authoritative value
        "token_usage": {"input": 100, "output": 50, "total": 150},
    }]
    out = compute_outline(
        conversation=[],
        events=[completed_event],
        trace=explicit_trace,
        todo_steps={},
        agents_snapshot=[{"name": "scout"}],
        dag=dag,
        iter_index={"scout": [{"iter": 1}]},
    )
    item = out[0]
    # Explicit trace wins → 1111 not 9999.
    assert item["activity"]["durationMs"] == 1111
    token_badges = [b for b in item["badges"] if b["kind"] == "tokens"]
    assert len(token_badges) == 1
    assert token_badges[0]["text"] == "150"  # explicit trace's total


def test_outline_no_badge_when_node_never_completed():
    """Node that started but hasn't completed yet → no token/duration badge.
    (No node.completed event in buffer → no trace data.)"""
    dag = {"nodes": ["scout"], "edges": []}
    out = compute_outline(
        conversation=[],
        events=[],  # no completion event
        trace=[],
        todo_steps={},
        agents_snapshot=[{"name": "scout"}],
        dag=dag,
        iter_index={"scout": [{"iter": 1}]},
    )
    item = out[0]
    # No tokens badge (no completion to derive from).
    assert not any(b["kind"] == "tokens" for b in item["badges"])
    # Activity is idle (no completion, no running status).
    assert item["activity"] == {"kind": "idle"}
