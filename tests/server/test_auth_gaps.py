"""Verify the 3 known auth gaps are closed.

Audit findings:
1. POST /api/profiles (save_profile) — silently used "default" for anon requests
2. POST /api/charts (chart_render) — silently used "default" for anon requests
3. Batch WebSocket endpoint — accepted `anon-XXX` identifiers as a fallback

These aren't necessarily admin-only — they just need to know who the user is.
The fix rejects requests that don't identify themselves, instead of silently
acting as the "default" user.
"""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_save_profile_rejects_missing_auth(client):
    """save_profile without X-User-Id should not silently use 'default'."""
    r = client.post("/api/profiles", json={
        "name": "test-profile",
        "model": "gpt-4",
    })
    # Should reject — either 401, 403, or 422
    assert r.status_code in (401, 403, 422), f"Got {r.status_code}: {r.text}"


def test_chart_render_rejects_missing_auth(client):
    """chart_render without X-User-Id should reject."""
    r = client.post("/api/charts", json={
        "node_id": "test-node",
        "chart": {"chart_type": "bar", "data": [{"x": 1, "y": 2}]},
    })
    assert r.status_code in (401, 403, 422), f"Got {r.status_code}: {r.text}"


def test_save_profile_works_with_user_id(client):
    """Authenticated request still succeeds (i.e. not 401/403)."""
    r = client.post("/api/profiles", json={
        "name": "test-profile-auth",
        "model": "gpt-4",
    }, headers={"X-User-Id": "default"})
    # May fail for unrelated reasons (e.g. profile validation), but not auth
    assert r.status_code != 401, f"Got 401: {r.text}"
    assert r.status_code != 403, f"Got 403: {r.text}"


def test_chart_render_works_with_user_id(client):
    """Authenticated request still succeeds (i.e. not 401/403).

    chart_render doesn't strictly need a real user — but with the fix, sending
    X-User-Id should bypass the auth check and reach the routing logic.
    """
    r = client.post("/api/charts", json={
        "node_id": "test-node",
        "chart": {"chart_type": "bar", "data": [{"x": 1, "y": 2}]},
    }, headers={"X-User-Id": "default"})
    assert r.status_code != 401, f"Got 401: {r.text}"
    assert r.status_code != 403, f"Got 403: {r.text}"


def test_chart_render_allows_localhost(client, monkeypatch):
    """chart_render allows localhost callers without auth.

    chart_render has two callers: external (browser → frontend, requires
    X-User-Id) and internal (worker subprocess → server via
    HARNESS_SERVER_URL=127.0.0.1, no user identity). We allow localhost to
    bypass auth so the server-to-server fallback path keeps working.
    """
    # Patch request.client to look like 127.0.0.1, simulating a real internal
    # call from the worker subprocess.
    from starlette.requests import Request as StarletteRequest

    original_client = StarletteRequest.client.fget

    @property
    def fake_client(self):
        # Address is a namedtuple — use _replace to swap host.
        client = original_client(self)
        return client._replace(host="127.0.0.1") if client else None

    # Only patch if testclient isn't already localhost (it's "testclient")
    monkeypatch.setattr(StarletteRequest, "client", fake_client)

    r = client.post("/api/charts", json={
        "node_id": "test-node",
        "chart": {"chart_type": "bar", "data": [{"x": 1, "y": 2}]},
    })
    assert r.status_code != 401, f"Got 401: {r.text}"
    assert r.status_code != 403, f"Got 403: {r.text}"


def test_batch_ws_rejects_anon_identifier(client):
    """Batch WS should reject requests where user_id resolves to 'anon-' prefix.

    The batch endpoint at /ws/batch/{batch_id} previously fell back to
    generating `anon-{uuid}` identifiers when no user_id was provided. This
    allowed unauthenticated clients to subscribe to events. The fix rejects
    such connections at the protocol level (close code 1008 / 4401).

    We test this by attempting a connection without user_id/api_key and
    verifying it does NOT establish — the server should close before the
    handshake completes.
    """
    # TestClient treats failed WS as RuntimeError with WebSocketDisconnect
    from starlette.websockets import WebSocketDisconnect

    # Use a valid-format batch_id path; the WS auth check should run before
    # the batch lookup, so any batch_id string works here.
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/batch/nonexistent-batch"):
            # If the connection establishes and we get here, the auth
            # check did not run. Force-fail.
            pass
    # 1008 = policy violation, 4401 = custom auth-reject code, 4004 = batch
    # not found (would mean auth check passed but batch didn't exist — also a
    # failure of the auth gate, since anon was let through to batch lookup).
    assert exc_info.value.code in (1008, 4401), (
        f"Expected rejection close code, got {exc_info.value.code}"
    )


def test_batch_ws_rejects_explicit_anon_user_id(client):
    """Even an explicit user_id=anon-XXX should be rejected."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/batch/nonexistent-batch?user_id=anon-intruder"
        ):
            pass
    assert exc_info.value.code in (1008, 4401), (
        f"Expected rejection close code, got {exc_info.value.code}"
    )
