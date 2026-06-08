"""Tests for @require_admin via Depends()."""
import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient

from server.auth import require_admin_dep
from harness.user_manager import User


def test_require_admin_blocks_non_admin():
    """Non-admin user gets 403."""
    app = FastAPI()

    @app.delete("/users/{uid}")
    async def delete_user(uid: str, _admin: None = Depends(require_admin_dep)):
        return {"deleted": uid}

    client = TestClient(app)
    r = client.delete("/users/x", headers={"X-User-Id": "default"})
    assert r.status_code == 403


def test_require_admin_allows_admin():
    """Admin user passes through."""
    app = FastAPI()

    @app.delete("/users/{uid}")
    async def delete_user(uid: str, _admin: None = Depends(require_admin_dep)):
        return {"deleted": uid}

    client = TestClient(app)
    r = client.delete("/users/x", headers={"X-API-Key": "admin"})
    assert r.status_code == 200
    assert r.json() == {"deleted": "x"}


def test_require_admin_dep_returns_none_on_success():
    """The dep returns None (or the User) on success — handler doesn't need it."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint(_admin: None = Depends(require_admin_dep)):
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/test", headers={"X-API-Key": "admin"})
    assert r.status_code == 200
