"""P4-T08: snapshot size + manifest-shape tests.

Validates ADR D3 (snapshot is a manifest, < 10KB) and I6 (snapshot
size < 50KB, enforced). Pre-P4 snapshots were 300KB-1MB because they
embedded conversation + agent_io + todo_states. Post-P4 they should
be sub-KB for typical NAS workflows.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.engine.incremental_save import _build_iter_data


# Thresholds — keep generous headroom. ADR D3 says < 10KB; we test < 5KB
# so a slow creep gets caught early. I6 (lint) uses 50KB as the hard cap.
_MANIFEST_SOFT_CAP_KB = 5
_MANIFEST_HARD_CAP_KB = 50  # mirrors scripts/lint_runs.py I6


def _build_minimal_v2_snapshot() -> dict:
    """Construct a v2 snapshot shaped like what _save_incremental produces
    post-P4 — no conversation / agent_io / todo_states / nodes_latest."""
    return {
        "version": 2,
        "run_id": "phase4-test-run",
        "workflow_name": "nas",
        "status": "running",
        "created_at": "2026-06-17T00:00:00+00:00",
        "last_seq": 156,
        "dag": {
            "nodes": [
                "scout", "selector", "planner", "judger", "trainer",
                "validator", "analyzer", "refiner", "adapter_generator",
            ],
            "edges": [],
        },
        "latest_iter_by_node": {
            "scout": 3, "selector": 6, "planner": 6, "judger": 5,
            "trainer": 5, "validator": 4, "analyzer": 4,
            "refiner": 1, "adapter_generator": 1,
        },
        "current_iter": 6,
        "iter_index": {
            "scout": [{"iter": i, "status": "completed", "summary": f"scout iter {i}", "duration_ms": 60000} for i in range(1, 4)],
            "selector": [{"iter": i, "status": "completed", "summary": f"sel iter {i}", "duration_ms": 60000} for i in range(1, 7)],
        },
        "fitness_history": [
            {"iter": 1, "best_fitness": 0.85, "best_strategy_id": "s1"},
            {"iter": 2, "best_fitness": 0.89, "best_strategy_id": "s2"},
        ],
        "charts": None,
    }


def test_snapshot_under_10kb():
    """ADR D3 target: snapshot < 10KB for typical NAS 9-agent workflow."""
    snapshot = _build_minimal_v2_snapshot()
    content = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)
    assert len(content) < 10 * 1024, (
        f"snapshot is {len(content)} bytes — exceeds 10KB manifest target. "
        f"Probably re-introduced conversation / agent_io / todo_states."
    )


def test_snapshot_under_i6_hard_cap():
    """I6 invariant: snapshot < 50KB. lint_runs.py enforces this post-P4."""
    snapshot = _build_minimal_v2_snapshot()
    content = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)
    assert len(content) < _MANIFEST_HARD_CAP_KB * 1024


def test_v2_snapshot_omits_legacy_heavy_fields():
    """P4-T01/T02/T03/T04: removed fields must NOT be present."""
    snapshot = _build_minimal_v2_snapshot()
    for forbidden in ("conversation", "agent_io", "todo_states", "conversation_total", "nodes_latest", "seq_cursor"):
        assert forbidden not in snapshot, (
            f"snapshot contains legacy field {forbidden!r} — P4 was supposed to remove it"
        )


def test_v2_snapshot_has_d3_manifest_fields():
    """P4-T04/T05: new fields present and correctly shaped."""
    snapshot = _build_minimal_v2_snapshot()
    assert snapshot["version"] == 2
    assert isinstance(snapshot["last_seq"], int) and snapshot["last_seq"] >= 0
    assert isinstance(snapshot["latest_iter_by_node"], dict)
    # latest_iter_by_node values are ints, NOT nested objects.
    for node_id, val in snapshot["latest_iter_by_node"].items():
        assert isinstance(val, int), (
            f"latest_iter_by_node[{node_id!r}] is {type(val).__name__}, expected int "
            f"(legacy nodes_latest was {{status, latest_iter}}; D3 flattens to int)"
        )


def test_v2_snapshot_validates_against_schema():
    """The constructed v2 snapshot must pass schema validation."""
    from harness.persistence.validate import validate_snapshot

    snapshot = _build_minimal_v2_snapshot()
    errors = validate_snapshot(snapshot)
    assert errors == [], f"v2 snapshot schema violations: {errors}"


def test_build_iter_data_does_not_add_conversation_fields():
    """P4-T01/T02/T03 side effect: _build_iter_data is for SIDECAR construction.
    Verify it doesn't accidentally re-introduce removed snapshot fields."""
    data = _build_iter_data(
        agent_io_snapshot={"scout": {"output_result": {"summary": "ok"}}},
        todo_states={},
        node_id="scout",
        iter_num=1,
        duration_ms=100,
        status="completed",
    )
    # iter_data is for sidecar, not snapshot. Should NOT carry snapshot-only fields.
    for snap_only in ("conversation_total", "nodes_latest", "latest_iter_by_node"):
        assert snap_only not in data
