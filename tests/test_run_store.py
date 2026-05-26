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
