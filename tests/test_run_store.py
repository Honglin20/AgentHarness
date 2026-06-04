import json
import tempfile
from pathlib import Path

from harness.run_store import RunStore


def test_save_and_list_runs():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)

        store.save(
            run_id="run-001",
            workflow_name="code_review",
            agents_snapshot=[{"name": "analyzer", "after": [], "md_content": "You are an analyzer."}],
            status="completed",
            inputs={"task": "review foo"},
            result={"outputs": {"analyzer": "ok"}, "errors": {}, "trace": []},
        )

        store.save(
            run_id="run-002",
            workflow_name="code_review",
            agents_snapshot=[{"name": "analyzer", "after": [], "md_content": "You are a code analyzer."}],
            status="completed",
            inputs={"task": "review bar"},
            result={"outputs": {"analyzer": "done"}, "errors": {}, "trace": []},
        )

        store.save(
            run_id="run-003",
            workflow_name="research",
            agents_snapshot=[{"name": "analyzer", "after": [], "md_content": "You are a researcher."}],
            status="failed",
            inputs={"task": "research baz"},
            result=None,
        )

        runs = store.list_runs()
        assert len(runs) == 3
        assert runs[0]["run_id"] == "run-003"
        assert runs[1]["run_id"] == "run-002"
        assert runs[2]["run_id"] == "run-001"

        cr_runs = store.list_runs(workflow_name="code_review")
        assert len(cr_runs) == 2

        run = store.get_run("run-001")
        assert run["workflow_name"] == "code_review"
        assert run["agents_snapshot"][0]["md_content"] == "You are an analyzer."


def test_list_runs_filters_by_user():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)

        store.save(
            run_id="run-alice", workflow_name="code_review",
            agents_snapshot=[], status="completed", inputs={}, result=None,
            user_id="alice",
        )
        store.save(
            run_id="run-bob", workflow_name="code_review",
            agents_snapshot=[], status="completed", inputs={}, result=None,
            user_id="bob",
        )
        store.save(
            run_id="run-no-user", workflow_name="code_review",
            agents_snapshot=[], status="completed", inputs={}, result=None,
        )

        alice_runs = store.list_runs(user_id="alice")
        assert len(alice_runs) == 1
        assert alice_runs[0]["run_id"] == "run-alice"

        bob_runs = store.list_runs(user_id="bob")
        assert len(bob_runs) == 1
        assert bob_runs[0]["run_id"] == "run-bob"

        all_runs = store.list_runs()
        assert len(all_runs) == 3


def test_list_runs_combines_user_and_workflow_filter():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)

        store.save(
            run_id="run-1", workflow_name="code_review",
            agents_snapshot=[], status="completed", inputs={}, result=None,
            user_id="alice",
        )
        store.save(
            run_id="run-2", workflow_name="research",
            agents_snapshot=[], status="completed", inputs={}, result=None,
            user_id="alice",
        )

        alice_cr = store.list_runs(user_id="alice", workflow_name="code_review")
        assert len(alice_cr) == 1
        assert alice_cr[0]["run_id"] == "run-1"


def test_get_run_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        assert store.get_run("nonexistent") is None


def test_save_and_retrieve_chart_groups():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        chart_groups = {
            "groups": {
                "Run Summary": {
                    "label": "Run Summary",
                    "collapsed": False,
                    "charts": {
                        "Tokens": {
                            "title": "Tokens",
                            "chart_type": "bar",
                            "data": [{"agent": "a1", "tokens": 100}],
                            "columns": ["agent", "tokens"],
                            "x": "agent",
                            "y": "tokens",
                        }
                    },
                    "table": None,
                }
            },
            "groupOrder": ["Run Summary"],
        }
        store.save(
            run_id="run-charts",
            workflow_name="test",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
            chart_groups=chart_groups,
        )
        run = store.get_run("run-charts")
        assert run["chart_groups"]["groupOrder"] == ["Run Summary"]
        assert "Tokens" in run["chart_groups"]["groups"]["Run Summary"]["charts"]


def test_save_and_retrieve_conversation():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        conversation = [
            {"id": "msg-1", "type": "agent", "content": "Hello", "agentName": "bot", "status": "done", "timestamp": 1000},
            {"id": "msg-2", "type": "tool_call", "content": "", "toolName": "bash", "toolArgs": {"cmd": "ls"}, "toolStatus": "done", "toolResult": "file.txt", "timestamp": 2000},
        ]
        store.save(
            run_id="run-conv",
            workflow_name="test",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
            conversation=conversation,
        )
        run = store.get_run("run-conv")
        assert len(run["conversation"]) == 2
        assert run["conversation"][0]["content"] == "Hello"
        assert run["conversation"][1]["toolName"] == "bash"


def test_save_preserves_created_at():
    """save() with created_at parameter preserves the original timestamp."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        original_ts = "2026-01-01T00:00:00+00:00"
        store.save(
            "inc-test", "wf", [], "running", {}, None,
            created_at=original_ts,
        )
        r1 = store.get_run("inc-test")
        assert r1["created_at"] == original_ts

        # Overwrite with more data — created_at should stay the same
        store.save(
            "inc-test", "wf", [], "running", {}, None,
            agent_io={"node_a": {"output": "hello"}},
            created_at=original_ts,
        )
        r2 = store.get_run("inc-test")
        assert r2["created_at"] == original_ts
        assert r2["agent_io"] == {"node_a": {"output": "hello"}}


def test_save_without_chart_groups_or_conversation():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        store.save(
            run_id="run-minimal",
            workflow_name="test",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
        )
        run = store.get_run("run-minimal")
        assert "chart_groups" not in run
        assert "conversation" not in run


def test_save_with_events(tmp_path):
    """RunStore.save() should persist the events list."""
    store = RunStore(str(tmp_path))
    events = [
        {"type": "agent.text_delta", "ts": 1000, "payload": {"text": "hello"}},
        {"type": "agent.tool_call", "ts": 1001, "payload": {"tool_name": "bash"}},
    ]
    store.save(
        run_id="evt-run-1",
        workflow_name="demo",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        events=events,
    )
    loaded = store.get_run("evt-run-1")
    assert loaded is not None
    assert loaded["events"] == events


def test_get_run_without_events_backward_compat(tmp_path):
    """Existing runs without events field should load fine."""
    store = RunStore(str(tmp_path))
    store.save(
        run_id="old-run-1",
        workflow_name="demo",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
    )
    loaded = store.get_run("old-run-1")
    assert loaded is not None
    assert "events" not in loaded


def test_atomic_write_produces_valid_json(tmp_path):
    """Atomic write should produce a valid JSON file."""
    store = RunStore(str(tmp_path))
    store.save(
        run_id="atomic-1",
        workflow_name="test",
        agents_snapshot=[],
        status="completed",
        inputs={"x": 1},
        result=None,
    )
    raw = (tmp_path / "atomic-1.json").read_text()
    data = json.loads(raw)
    assert data["run_id"] == "atomic-1"
    assert data["inputs"] == {"x": 1}


def test_atomic_write_overwrite_preserves_data(tmp_path):
    """Overwriting an existing record should not corrupt it."""
    store = RunStore(str(tmp_path))
    store.save(
        run_id="overwrite-1",
        workflow_name="test",
        agents_snapshot=[],
        status="running",
        inputs={},
        result=None,
    )
    store.save(
        run_id="overwrite-1",
        workflow_name="test",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result={"outputs": {"a": "done"}},
        agent_io={"a": {"output": "hello"}},
    )
    run = store.get_run("overwrite-1")
    assert run["status"] == "completed"
    assert run["agent_io"] == {"a": {"output": "hello"}}


def test_corrupted_file_skipped_with_warning(tmp_path):
    """Corrupted JSON files should be skipped gracefully."""
    store = RunStore(str(tmp_path))

    # Write a valid run
    store.save(
        run_id="valid-1",
        workflow_name="test",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
    )

    # Manually create a corrupted file
    (tmp_path / "corrupted-1.json").write_text("{invalid json content")

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "valid-1"


def test_stale_tmp_files_cleaned_up(tmp_path):
    """list_runs should clean up stale .json.tmp files."""
    import time as _time
    import os

    store = RunStore(str(tmp_path))

    # Create a stale tmp file (old mtime)
    tmp_file = tmp_path / "stale-run.json.tmp"
    tmp_file.write_text("stale")
    # Set mtime to 10 minutes ago
    old_time = _time.time() - 600
    os.utime(tmp_file, (old_time, old_time))

    # list_runs should clean it up
    store.list_runs()
    assert not tmp_file.exists()


def test_no_tmp_left_after_successful_save(tmp_path):
    """Successful save should not leave .tmp files behind."""
    store = RunStore(str(tmp_path))
    store.save(
        run_id="no-tmp",
        workflow_name="test",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
    )
    tmp_files = list(tmp_path.glob("*.json.tmp"))
    assert len(tmp_files) == 0
