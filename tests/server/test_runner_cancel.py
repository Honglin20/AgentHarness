"""Tests for runner.cancel() pause persistence."""
import pytest
from pathlib import Path


def test_cancel_preserves_agent_io(tmp_path):
    """Pausing a run preserves agent_io from incremental save."""
    from harness.run_store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    run_id = "test-cancel-preserve"

    # Simulate incremental save (what _save_incremental does after each node)
    store.save(
        run_id=run_id,
        workflow_name="test_wf",
        agents_snapshot=[{"name": "a", "after": []}],
        status="running",
        inputs={"task": "x"},
        result=None,
        dag={"nodes": ["a"], "edges": [], "conditional_edges": []},
        agent_io={"a": {"input_prompt": "ctx", "output_result": "out", "system_prompt": "sys"}},
        conversation=[{"type": "agent", "nodeId": "a", "content": "hello"}],
    )

    # Verify the running record has agent_io
    running = store.get_run(run_id)
    assert running["agent_io"]["a"]["input_prompt"] == "ctx"

    # Simulate what cancel() does: read existing record, save as paused preserving data
    existing = store.get_run(run_id)
    store.save(
        run_id=run_id,
        workflow_name="test_wf",
        agents_snapshot=existing.get("agents_snapshot", []),
        status="paused",
        inputs=existing.get("inputs", {}),
        result=existing.get("result"),
        dag=existing.get("dag"),
        agent_io=existing.get("agent_io"),
        conversation=existing.get("conversation"),
        events=existing.get("events"),
    )

    paused = store.get_run(run_id)
    assert paused["status"] == "paused"
    assert paused["agent_io"]["a"]["input_prompt"] == "ctx"
    assert paused["conversation"][0]["content"] == "hello"


def test_cancel_preserves_events(tmp_path):
    """Pausing a run preserves events buffer from incremental save."""
    from harness.run_store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    run_id = "test-cancel-events"

    # Save with events (simulating _save_incremental or completion save)
    store.save(
        run_id=run_id,
        workflow_name="test_wf",
        agents_snapshot=[],
        status="running",
        inputs={},
        result=None,
        events=[
            {"type": "node.started", "payload": {"node_id": "a"}},
            {"type": "node.completed", "payload": {"node_id": "a", "output_result": "done"}},
        ],
    )

    # Simulate cancel: read existing record + events sidecar, save as paused
    existing = store.get_run(run_id)
    persisted_events = store.get_events(run_id)
    store.save(
        run_id=run_id,
        workflow_name="test_wf",
        agents_snapshot=existing.get("agents_snapshot", []),
        status="paused",
        inputs=existing.get("inputs", {}),
        result=existing.get("result"),
        events=persisted_events,
    )

    paused = store.get_run(run_id)
    assert paused["status"] == "paused"
    # Events live in a sidecar file since Phase 4 (main record only has _has_events flag).
    assert paused.get("_has_events") is True
    reloaded_events = store.get_events(run_id)
    assert len(reloaded_events) == 2
    assert reloaded_events[0]["type"] == "node.started"


def test_run_store_persists_work_dir(tmp_path):
    """RunStore.save() persists work_dir and get_run() returns it."""
    from harness.run_store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    store.save(
        run_id="test-workdir",
        workflow_name="wf",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        work_dir="/tmp/some_project",
    )

    record = store.get_run("test-workdir")
    assert record["work_dir"] == "/tmp/some_project"


def test_run_store_work_dir_none_not_persisted(tmp_path):
    """When work_dir is None, the record holds None (Phase 4: key always present
    so frontend can rely on the shape; value None means 'no work_dir')."""
    from harness.run_store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    store.save(
        run_id="test-no-workdir",
        workflow_name="wf",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
    )

    record = store.get_run("test-no-workdir")
    assert record.get("work_dir") is None
