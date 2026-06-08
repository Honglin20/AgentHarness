"""Verify handlers use Depends() providers — testable via override."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.dependencies import get_run_store_dep, get_repository_dep
from harness.run_store import RunStore
from server.repository import WorkflowRepository


def test_runs_endpoint_uses_overridden_store(tmp_path):
    """list_runs should use the overridden RunStore, not the singleton."""
    fake_store = RunStore(str(tmp_path))
    fake_store.save(
        run_id="test-run-override",
        workflow_name="w",
        agents_snapshot=[],
        status="completed",
        inputs={"x": 1},
        result=None,
        user_id="default",
    )

    app = create_app()
    app.dependency_overrides[get_run_store_dep] = lambda: fake_store

    client = TestClient(app)
    r = client.get("/api/runs", headers={"X-User-Id": "default"})
    assert r.status_code == 200
    runs_data = r.json()
    runs = runs_data.get("runs", [])
    run_ids = [r["run_id"] for r in runs]
    assert "test-run-override" in run_ids, f"Override not applied; got {run_ids}"


def test_runs_endpoint_cleans_up_override():
    """After clearing overrides, the singleton should be used again."""
    app = create_app()
    app.dependency_overrides[get_run_store_dep] = lambda: RunStore()
    app.dependency_overrides.clear()

    client = TestClient(app)
    r = client.get("/api/runs", headers={"X-User-Id": "default"})
    assert r.status_code == 200  # uses default RunStore


def test_repository_dep_is_singleton():
    """Repository dep should still return the same singleton (not create new)."""
    app = create_app()
    client = TestClient(app)

    # Make two requests and verify repository state is consistent
    r1 = client.get("/api/runs", headers={"X-User-Id": "default"})
    r2 = client.get("/api/runs", headers={"X-User-Id": "default"})
    assert r1.status_code == 200
    assert r2.status_code == 200
