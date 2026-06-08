"""Tests for resume endpoint — cross-restart reconstruction path."""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


def test_reconstruct_run_to_repo_basic(tmp_path, monkeypatch):
    """_reconstruct_run_to_repo rebuilds a Workflow from disk record and injects into repo."""
    from harness.run_store import RunStore
    from server.repository import WorkflowRepository
    from server.routes import _reconstruct_run_to_repo

    # Persist a paused run with complete agents_snapshot
    store = RunStore(runs_dir=tmp_path / "runs")
    run_id = "test-restart-resume"
    store.save(
        run_id=run_id,
        workflow_name="code_review",
        agents_snapshot=[
            {"name": "reviewer", "after": [], "tools": None, "model": None, "retries": 3},
            {"name": "summarizer", "after": ["reviewer"], "tools": None, "model": None, "retries": 3},
        ],
        status="paused",
        inputs={"task": "review this code"},
        result=None,
        dag={"nodes": ["reviewer", "summarizer"], "edges": [["reviewer", "summarizer"]], "conditional_edges": []},
    )

    # Set up clean repo
    repo = WorkflowRepository()
    assert not repo.contains(run_id)

    # Mock user
    mock_user = MagicMock()
    mock_user.user_id = "default"
    mock_user.role = "admin"
    monkeypatch.setattr("server._helpers.get_current_user", lambda r: mock_user)
    monkeypatch.setattr("server._helpers.get_user_manager", lambda: MagicMock(is_admin=lambda u: True))

    # Patch RunStore to use our temp dir
    monkeypatch.setattr("harness.persistence.run_store._DEFAULT_RUNS_DIR", tmp_path / "runs")

    # Reconstruct
    record = store.get_run(run_id)
    mock_request = MagicMock()
    _reconstruct_run_to_repo(repo, run_id, record, mock_request)

    # Verify: run is in repo with correct workflow
    assert repo.contains(run_id)
    wf_data = repo.get(run_id)
    workflow = wf_data["workflow"]
    assert len(workflow.agents) == 2
    assert workflow.agents[0].name == "reviewer"
    assert workflow.agents[1].name == "summarizer"
    assert wf_data["status"] == "paused"
    assert repo.get_dag(run_id) is not None


def test_reconstruct_preserves_conditional_edges(tmp_path, monkeypatch):
    """_reconstruct_run_to_repo preserves on_pass/on_fail from agents_snapshot."""
    from harness.run_store import RunStore
    from server.repository import WorkflowRepository
    from server.routes import _reconstruct_run_to_repo

    store = RunStore(runs_dir=tmp_path / "runs")
    run_id = "test-conditional-restart"
    store.save(
        run_id=run_id,
        workflow_name="conditional_route",
        agents_snapshot=[
            {"name": "analyzer", "after": [], "tools": None, "model": None, "retries": 3},
            {"name": "classifier", "after": ["analyzer"], "tools": None, "model": None, "retries": 3,
             "on_pass": "summary", "on_fail": "debugger"},
            {"name": "summary", "after": [], "tools": None, "model": None, "retries": 3},
            {"name": "debugger", "after": [], "tools": ["bash"], "model": None, "retries": 3},
        ],
        status="paused",
        inputs={"task": "test"},
        result=None,
        dag={"nodes": ["analyzer", "classifier", "summary", "debugger"],
             "edges": [["analyzer", "classifier"]],
             "conditional_edges": [{"from": "classifier", "to": "summary", "label": "pass"},
                                   {"from": "classifier", "to": "debugger", "label": "fail"}]},
    )

    repo = WorkflowRepository()
    mock_user = MagicMock()
    mock_user.user_id = "default"
    mock_user.role = "admin"
    monkeypatch.setattr("server._helpers.get_current_user", lambda r: mock_user)
    monkeypatch.setattr("server._helpers.get_user_manager", lambda: MagicMock(is_admin=lambda u: True))
    monkeypatch.setattr("harness.persistence.run_store._DEFAULT_RUNS_DIR", tmp_path / "runs")

    record = store.get_run(run_id)
    _reconstruct_run_to_repo(repo, run_id, record, MagicMock())

    wf_data = repo.get(run_id)
    workflow = wf_data["workflow"]
    classifier = [a for a in workflow.agents if a.name == "classifier"][0]
    assert classifier.on_pass == "summary"
    assert classifier.on_fail == "debugger"


def test_reconstruct_preserves_work_dir(tmp_path, monkeypatch):
    """_reconstruct_run_to_repo preserves work_dir from disk record."""
    from harness.run_store import RunStore
    from server.repository import WorkflowRepository
    from server.routes import _reconstruct_run_to_repo

    store = RunStore(runs_dir=tmp_path / "runs")
    run_id = "test-workdir-restart"
    store.save(
        run_id=run_id,
        workflow_name="code_review",
        agents_snapshot=[{"name": "reviewer", "after": []}],
        status="paused",
        inputs={},
        result=None,
        work_dir="/tmp/my_project",
    )

    repo = WorkflowRepository()
    mock_user = MagicMock()
    mock_user.user_id = "default"
    mock_user.role = "admin"
    monkeypatch.setattr("server._helpers.get_current_user", lambda r: mock_user)
    monkeypatch.setattr("server._helpers.get_user_manager", lambda: MagicMock(is_admin=lambda u: True))
    monkeypatch.setattr("harness.persistence.run_store._DEFAULT_RUNS_DIR", tmp_path / "runs")

    record = store.get_run(run_id)
    _reconstruct_run_to_repo(repo, run_id, record, MagicMock())

    wf_data = repo.get(run_id)
    assert wf_data["work_dir"] == "/tmp/my_project"


def test_reconstruct_rejects_wrong_user(tmp_path, monkeypatch):
    """_reconstruct_run_to_repo rejects non-owner users."""
    from harness.run_store import RunStore
    from server.repository import WorkflowRepository
    from server.routes import _reconstruct_run_to_repo
    from fastapi import HTTPException

    store = RunStore(runs_dir=tmp_path / "runs")
    run_id = "test-auth-reject"
    store.save(
        run_id=run_id,
        workflow_name="code_review",
        agents_snapshot=[{"name": "a", "after": []}],
        status="paused",
        inputs={},
        result=None,
        user_id="alice",
    )

    repo = WorkflowRepository()
    mock_user = MagicMock()
    mock_user.user_id = "bob"
    mock_user.role = "developer"
    monkeypatch.setattr("server._helpers.get_current_user", lambda r: mock_user)
    monkeypatch.setattr("server._helpers.get_user_manager", lambda: MagicMock(is_admin=lambda u: False))
    monkeypatch.setattr("harness.persistence.run_store._DEFAULT_RUNS_DIR", tmp_path / "runs")

    record = store.get_run(run_id)
    with pytest.raises(HTTPException) as exc_info:
        _reconstruct_run_to_repo(repo, run_id, record, MagicMock())
    assert exc_info.value.status_code == 403
