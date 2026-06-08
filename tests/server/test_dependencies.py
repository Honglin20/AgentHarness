"""Tests for FastAPI dependency providers."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from server.dependencies import (
    get_run_store_dep,
    get_event_bus_dep,
    get_user_manager_dep,
    get_runner_dep,
    get_repository_dep,
    get_current_user_dep,
)
from harness.run_store import RunStore
from harness.extensions.bus import Bus
from harness.user_manager import UserManager
from server.runner import WorkflowRunner
from server.repository import WorkflowRepository


def test_get_run_store_dep_returns_run_store():
    s = get_run_store_dep()
    assert isinstance(s, RunStore)


def test_get_run_store_dep_returns_singleton():
    """Two calls to get_run_store_dep should return the same instance.

    RunStore.__init__ calls mkdir; creating one per request is wasteful and
    can race on the runs directory. The provider must cache the singleton.
    """
    s1 = get_run_store_dep()
    s2 = get_run_store_dep()
    assert s1 is s2


def test_get_repository_dep_returns_singleton():
    r1 = get_repository_dep()
    r2 = get_repository_dep()
    assert r1 is r2
    assert isinstance(r1, WorkflowRepository)


def test_get_event_bus_dep_returns_bus():
    b = get_event_bus_dep()
    assert isinstance(b, Bus)


def test_get_runner_dep_returns_runner():
    r = get_runner_dep()
    assert isinstance(r, WorkflowRunner)


def test_get_user_manager_dep_returns_user_manager():
    m = get_user_manager_dep()
    assert isinstance(m, UserManager)


def test_dependency_override_works():
    """FastAPI Depends() should allow test-time override."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint(store: RunStore = Depends(get_run_store_dep)):
        return {"type": type(store).__name__}

    fake_store = RunStore()
    app.dependency_overrides[get_run_store_dep] = lambda: fake_store

    client = TestClient(app)
    r = client.get("/test")
    assert r.status_code == 200
    assert r.json() == {"type": "RunStore"}


def test_get_current_user_dep_extracts_from_request():
    """User dependency should read X-User-Id header."""
    app = FastAPI()

    @app.get("/me")
    async def me(user=Depends(get_current_user_dep)):
        return {"user_id": user.user_id}

    client = TestClient(app)
    r = client.get("/me", headers={"X-User-Id": "default"})
    assert r.status_code == 200
    assert r.json()["user_id"] == "default"
