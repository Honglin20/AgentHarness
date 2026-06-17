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

        runs_result = store.list_runs()
        runs = runs_result["runs"]
        assert len(runs) == 3
        assert runs[0]["run_id"] == "run-003"
        assert runs[1]["run_id"] == "run-002"
        assert runs[2]["run_id"] == "run-001"

        cr_result = store.list_runs(workflow_name="code_review")
        cr_runs = cr_result["runs"]
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

        alice_result = store.list_runs(user_id="alice")
        alice_runs = alice_result["runs"]
        assert len(alice_runs) == 1
        assert alice_runs[0]["run_id"] == "run-alice"

        bob_result = store.list_runs(user_id="bob")
        bob_runs = bob_result["runs"]
        assert len(bob_runs) == 1
        assert bob_runs[0]["run_id"] == "run-bob"

        all_result = store.list_runs()
        all_runs = all_result["runs"]
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

        alice_cr_result = store.list_runs(user_id="alice", workflow_name="code_review")
        alice_cr = alice_cr_result["runs"]
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

        # Main record should NOT contain chart_groups
        run = store.get_run("run-charts")
        assert "chart_groups" not in run
        assert run["_has_charts"] is True

        # Charts are in sidecar
        charts = store.get_charts("run-charts")
        assert charts is not None
        assert charts["groupOrder"] == ["Run Summary"]
        assert "Tokens" in charts["groups"]["Run Summary"]["charts"]


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
        assert run.get("conversation") == []  # empty list, not None


def test_save_with_events(tmp_path):
    """RunStore.save() should persist events to sidecar."""
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
    run = store.get_run("evt-run-1")
    assert run is not None
    assert run["_has_events"] is True
    assert "events" not in run

    loaded = store.get_events("evt-run-1")
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0]["type"] == "agent.text_delta"


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
    assert "_has_events" in loaded
    assert loaded["_has_events"] is False


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

    runs_result = store.list_runs()
    runs = runs_result["runs"]
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


def test_chart_deduplication(tmp_path):
    """chart.render events should be deduplicated in events sidecar."""
    store = RunStore(str(tmp_path))
    big_chart_data = [{"x": i, "y": i * 2} for i in range(1000)]
    events = [
        {"type": "agent.text_delta", "ts": 1000, "payload": {"text": "hello"}},
        {
            "type": "chart.render",
            "ts": 1001,
            "payload": {
                "node_id": "agent1",
                "agent_name": "agent1",
                "chart": {
                    "label": "test",
                    "title": "Big Chart",
                    "chart_type": "bar",
                    "data": big_chart_data,
                },
            },
        },
        {"type": "node.completed", "ts": 1002, "payload": {"node_id": "agent1"}},
    ]
    chart_groups = {
        "groups": {"test": {"label": "test", "collapsed": False, "charts": {}, "table": None}},
        "groupOrder": ["test"],
    }
    store.save(
        run_id="dedup-1",
        workflow_name="test",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        chart_groups=chart_groups,
        events=events,
    )

    loaded_events = store.get_events("dedup-1")
    assert loaded_events is not None
    assert len(loaded_events) == 3

    # The chart.render event should have a lightweight reference instead of full data
    chart_event = loaded_events[1]
    assert chart_event["type"] == "chart.render"
    assert "chart_ref" in chart_event["payload"]
    assert chart_event["payload"]["chart_ref"]["title"] == "Big Chart"
    # The big data array should NOT be in the event
    assert "data" not in chart_event["payload"].get("chart", {})

    # Non-chart events should be unchanged
    assert loaded_events[0]["type"] == "agent.text_delta"
    assert loaded_events[2]["type"] == "node.completed"


def test_delete_run_removes_sidecars(tmp_path):
    """delete_run should remove main file and sidecar files."""
    store = RunStore(str(tmp_path))
    chart_groups = {
        "groups": {"g1": {"label": "g1", "collapsed": False, "charts": {}, "table": None}},
        "groupOrder": ["g1"],
    }
    events = [{"type": "agent.text_delta", "ts": 1, "payload": {"text": "hi"}}]
    store.save(
        run_id="del-me",
        workflow_name="test",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        chart_groups=chart_groups,
        events=events,
    )

    assert (tmp_path / "del-me.json").exists()
    assert (tmp_path / "del-me+charts.json").exists()
    assert (tmp_path / "del-me+events.json").exists()

    assert store.delete_run("del-me") is True
    assert not (tmp_path / "del-me.json").exists()
    assert not (tmp_path / "del-me+charts.json").exists()
    assert not (tmp_path / "del-me+events.json").exists()


def test_list_runs_skips_sidecar_files(tmp_path):
    """list_runs should only iterate main JSON files, not sidecars."""
    store = RunStore(str(tmp_path))
    store.save(
        run_id="run-1",
        workflow_name="test",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        chart_groups={"groups": {"g": {"label": "g", "collapsed": False, "charts": {}, "table": None}}, "groupOrder": ["g"]},
        events=[{"type": "test", "ts": 1, "payload": {}}],
    )
    # Sidecar files exist
    assert (tmp_path / "run-1+charts.json").exists()
    assert (tmp_path / "run-1+events.json").exists()

    runs_result = store.list_runs()
    runs = runs_result["runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run-1"


def test_backward_compat_inline_chart_groups_migration(tmp_path):
    """Old-format files with inline chart_groups should be migrated on first read."""
    store = RunStore(str(tmp_path))

    # Write an old-format file with inline chart_groups and events
    old_record = {
        "run_id": "old-run",
        "workflow_name": "test",
        "agents_snapshot": [],
        "status": "completed",
        "inputs": {},
        "result": None,
        "chart_groups": {
            "groups": {"g": {"label": "g", "collapsed": False, "charts": {"c": {"title": "c", "chart_type": "bar", "data": [{"x": 1}]}}}},
            "groupOrder": ["g"],
        },
        "events": [{"type": "agent.text_delta", "ts": 1, "payload": {"text": "hi"}}],
        "conversation": [],
    }
    (tmp_path / "old-run.json").write_text(json.dumps(old_record, indent=2))

    # First read should trigger migration
    run = store.get_run("old-run")
    assert run is not None
    assert "chart_groups" not in run
    assert run["_has_charts"] is True
    assert run["_has_events"] is True

    # Sidecar files should now exist
    charts = store.get_charts("old-run")
    assert charts is not None
    assert "g" in charts["groups"]

    events = store.get_events("old-run")
    assert events is not None
    assert len(events) == 1


def test_list_runs_pagination(tmp_path):
    """list_runs should support limit/offset pagination."""
    store = RunStore(str(tmp_path))
    for i in range(10):
        store.save(
            run_id=f"run-{i:03d}",
            workflow_name="test",
            agents_snapshot=[],
            status="completed",
            inputs={"idx": i},
            result=None,
        )

    # First page
    page1 = store.list_runs(limit=4, offset=0)
    assert len(page1["runs"]) == 4
    assert page1["total"] == 10
    assert page1["has_more"] is True

    # Second page
    page2 = store.list_runs(limit=4, offset=4)
    assert len(page2["runs"]) == 4
    assert page2["has_more"] is True

    # Third page (partial)
    page3 = store.list_runs(limit=4, offset=8)
    assert len(page3["runs"]) == 2
    assert page3["has_more"] is False

    # No pagination — returns all
    all_runs = store.list_runs()
    assert len(all_runs["runs"]) == 10
    assert all_runs["total"] == 10
    assert all_runs["has_more"] is False


def test_save_and_get_outline_round_trip():
    """save_outline writes sidecar + _has_outline flag; get_outline reads it back."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        store.save(
            run_id="run-outline",
            workflow_name="demo",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
        )

        # No sidecar yet — get_outline returns None, _has_outline absent
        assert store.get_outline("run-outline") is None
        record = store.get_run("run-outline")
        assert record.get("_has_outline") in (None, False)

        outline = [
            {
                "key": "trainer__iter1",
                "node_id": "trainer",
                "iteration": 1,
                "is_latest_iter": True,
                "iter_count": 1,
                "name": "trainer",
                "first_ts": 1718000000000,
                "status": "completed",
                "activity": {"kind": "completed", "durationMs": 4500},
                "badges": [],
                "order": 0,
            }
        ]
        store.save_outline("run-outline", outline)

        # Round-trip: get_outline returns the same list
        loaded = store.get_outline("run-outline")
        assert loaded == outline

        # Flag stamped on main record
        record = store.get_run("run-outline")
        assert record.get("_has_outline") is True

        # Sidecar file uses the +outline.json suffix
        sidecar = Path(tmpdir) / "run-outline+outline.json"
        assert sidecar.exists()
        assert json.loads(sidecar.read_text()) == outline

        # list_runs glob should skip the sidecar (not treat it as a run)
        runs = store.list_runs()["runs"]
        assert all(r["run_id"] != "run-outline+outline" for r in runs)


def test_save_outline_with_empty_list_clears_sidecar():
    """Empty outline list removes the sidecar and clears _has_outline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        store.save(
            run_id="run-empty",
            workflow_name="demo",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
        )
        store.save_outline("run-empty", [{"key": "x__iter1"}])
        assert store.get_outline("run-empty") is not None
        assert store.get_run("run-empty").get("_has_outline") is True

        store.save_outline("run-empty", [])
        assert store.get_outline("run-empty") is None
        assert store.get_run("run-empty").get("_has_outline") is False


def test_delete_run_removes_outline_sidecar():
    """delete_run must clean up the +outline.json sidecar too."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)
        store.save(
            run_id="run-del",
            workflow_name="demo",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
        )
        store.save_outline("run-del", [{"key": "x__iter1"}])
        sidecar = Path(tmpdir) / "run-del+outline.json"
        assert sidecar.exists()

        assert store.delete_run("run-del") is True
        assert not sidecar.exists()


def test_index_rebuilds_after_external_write(tmp_path):
    """list_runs must pick up files written by external processes after the
    index was first built. Regression test for the macOS dir-mtime bug:
    atomic write (tmp + rename) doesn't always bump the directory's mtime,
    so the old dir-mtime invalidation never noticed new files arriving."""
    store = RunStore(runs_dir=str(tmp_path))

    # First call builds an empty index.
    assert store.list_runs(summary_only=True)["total"] == 0

    # External writer drops a main run record straight to disk (simulating
    # CLI runner / NAS workflow that doesn't go through store.save()).
    external_run = {
        "run_id": "ext-001",
        "workflow_name": "nas",
        "status": "running",
        "inputs": {"task": "search"},
        "created_at": "2026-06-17T00:00:00Z",
    }
    (tmp_path / "ext-001.json").write_text(json.dumps(external_run))

    # Second call MUST rebuild and see the new run. Old code returned 0
    # because directory mtime didn't change.
    result = store.list_runs(summary_only=True)
    assert result["total"] == 1
    assert result["runs"][0]["run_id"] == "ext-001"


def test_index_ignores_sidecar_files(tmp_path):
    """Sidecars (charts/events/outline/snapshot/iter_index/iter sidecar)
    must not be indexed as run records. Snapshot files are the trickiest —
    they contain a run_id field, so without the suffix filter they would
    pollute the index with partial data and shadow the real main record."""
    store = RunStore(runs_dir=str(tmp_path))

    # Drop every kind of sidecar file directly to disk.
    (tmp_path / "run-x+charts.json").write_text(json.dumps({"groups": {}}))
    (tmp_path / "run-x+events.json").write_text("[]")
    (tmp_path / "run-x+outline.json").write_text(json.dumps([]))
    # Snapshot has a run_id — must NOT be picked up as a main record.
    (tmp_path / "run-x+snapshot.json").write_text(json.dumps({
        "run_id": "run-x",
        "workflow_name": "shadow",
        "status": "completed",
    }))
    (tmp_path / "run-x+iter_index.json").write_text(json.dumps({}))
    (tmp_path / "run-x+iters+selector+1.json").write_text(json.dumps({"iter": 1}))

    result = store.list_runs(summary_only=True)
    assert result["total"] == 0, "sidecars leaked into the index"


def test_index_skips_rebuild_when_unchanged(tmp_path):
    """list_runs called twice in a row (no writes between) must reuse the
    cached index rather than rescanning disk. Guards the perf invariant
    and confirms fingerprint equality short-circuits rebuild."""
    store = RunStore(runs_dir=str(tmp_path))
    store.save(
        run_id="run-1", workflow_name="w", agents_snapshot=[],
        status="completed", inputs={}, result=None,
    )

    store.list_runs(summary_only=True)
    cached = store._summary_index
    assert cached is not None

    store.list_runs(summary_only=True)
    # Same object identity = no rebuild.
    assert store._summary_index is cached


def test_index_rebuilds_when_main_record_overwritten(tmp_path):
    """Overwriting a main run record (e.g. status flip running→success)
    must invalidate the cached index entry. Catches the case where file
    set is unchanged but content (mtime) changed."""
    store = RunStore(runs_dir=str(tmp_path))
    store.save(
        run_id="run-1", workflow_name="w", agents_snapshot=[],
        status="running", inputs={}, result=None,
    )

    first = store.list_runs(summary_only=True)
    assert first["runs"][0]["status"] == "running"

    # External rewrite (not via store.save, so _update_index_entry doesn't
    # fire) — simulates another process touching the file.
    import time
    path = tmp_path / "run-1.json"
    old_mtime = path.stat().st_mtime
    data = json.loads(path.read_text())
    data["status"] = "success"
    path.write_text(json.dumps(data))
    # macOS file mtime is second-resolution — bump past it to be safe.
    new_mtime = path.stat().st_mtime
    if new_mtime <= old_mtime:
        time.sleep(1.1)
        import os
        os.utime(path, None)

    second = store.list_runs(summary_only=True)
    assert second["runs"][0]["status"] == "success", "overwrite didn't invalidate index"
