"""Verify raw request.json() sites are now Pydantic-validated.

Endpoints that previously used `body = await request.json()` + manual
validation should now use FastAPI's typed body parameter. This gives:
  - 422 on missing required fields (instead of 400 from manual check)
  - 422 on wrong-type fields
  - Correct OpenAPI request body schema

Each test below targets one endpoint, sending a malformed payload and
asserting a 422 response (the FastAPI/Pydantic validation status).
"""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


# ── POST /api/users (create_user) ─────────────────────────────────────────


def test_create_user_rejects_missing_fields(client):
    """Missing user_id should return 422, not 400 from manual check."""
    r = client.post(
        "/api/users",
        json={"name": "x"},  # missing user_id
        headers={"X-API-Key": "admin"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_create_user_rejects_wrong_type_role(client):
    """role must be a string enum, not a number."""
    r = client.post(
        "/api/users",
        json={"user_id": "x", "name": "y", "role": 123},
        headers={"X-API-Key": "admin"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_create_user_rejects_non_string_user_id(client):
    """user_id must be a string, not a number."""
    r = client.post(
        "/api/users",
        json={"user_id": 123, "name": "y"},
        headers={"X-API-Key": "admin"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── POST /api/config (set_config) ─────────────────────────────────────────


def test_set_config_rejects_non_dict_inputs(client):
    """persist must be a bool, not a string."""
    r = client.post(
        "/api/config",
        json={"persist": "not-a-bool"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_set_config_rejects_wrong_type_thinking(client):
    """thinking must be a bool, not a number."""
    r = client.post(
        "/api/config",
        json={"thinking": 99},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── POST /api/profiles (save_profile) ─────────────────────────────────────


def test_save_profile_rejects_missing_name(client):
    """Profile without a name should 422, not 400."""
    r = client.post(
        "/api/profiles",
        json={"model": "gpt-4"},  # missing name
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_save_profile_rejects_wrong_type_proxy_enabled(client):
    """proxy_enabled must be a bool."""
    r = client.post(
        "/api/profiles",
        json={"name": "x", "proxy_enabled": "yes"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── PUT /api/profiles/{name}/rename ───────────────────────────────────────


def test_rename_profile_rejects_missing_new_name(client):
    """Missing new_name should 422, not 400."""
    r = client.put(
        "/api/profiles/old-name/rename",
        json={},  # missing new_name
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_rename_profile_rejects_wrong_type(client):
    """new_name must be a string, not a number."""
    r = client.put(
        "/api/profiles/old-name/rename",
        json={"new_name": 42},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── PUT /api/agents/{name}/md (update_agent_md) ──────────────────────────


def test_update_agent_md_rejects_missing_workflow(client):
    """Missing workflow should 422, not 400."""
    r = client.put(
        "/api/agents/some-agent/md",
        json={"md_content": "..."},  # missing workflow
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_update_agent_md_rejects_bad_target(client):
    """target must be 'private' or 'shared', not arbitrary."""
    r = client.put(
        "/api/agents/some-agent/md",
        json={"md_content": "...", "workflow": "wf", "target": "bogus"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── POST /api/charts (chart_render) ───────────────────────────────────────


def test_chart_render_rejects_non_dict_chart(client):
    """chart must be a dict (object), not a string."""
    r = client.post(
        "/api/charts",
        json={"node_id": "n", "chart": "not-a-dict"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── POST /api/runs/batch-delete ───────────────────────────────────────────


def test_batch_delete_runs_rejects_non_list(client):
    """run_ids must be a list of strings."""
    r = client.post(
        "/api/runs/batch-delete",
        json={"run_ids": "not-a-list"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_batch_delete_runs_rejects_missing_field(client):
    """Missing run_ids should 422."""
    r = client.post(
        "/api/runs/batch-delete",
        json={},  # missing run_ids
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_batch_delete_runs_rejects_non_string_element(client):
    """run_ids elements must be strings."""
    r = client.post(
        "/api/runs/batch-delete",
        json={"run_ids": [1, 2, 3]},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── PATCH /api/runs/{run_id}/conversation ────────────────────────────────


def test_update_run_conversation_rejects_non_list(client):
    """conversation must be a list."""
    r = client.patch(
        "/api/runs/some-run-id/conversation",
        json={"conversation": "not-a-list"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_update_run_conversation_rejects_missing_field(client):
    """Missing conversation should 422."""
    r = client.patch(
        "/api/runs/some-run-id/conversation",
        json={},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── PATCH /api/runs/{run_id}/charts ──────────────────────────────────────


def test_update_run_charts_rejects_non_dict(client):
    """chart_groups must be a dict or null, not a list."""
    r = client.patch(
        "/api/runs/some-run-id/charts",
        json={"chart_groups": ["not", "a", "dict"]},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── PATCH /api/runs/{run_id}/followup ────────────────────────────────────


def test_update_run_followup_rejects_missing_agent_name(client):
    """Missing agent_name should 422, not 400."""
    r = client.patch(
        "/api/runs/some-run-id/followup",
        json={"messages": []},  # missing agent_name
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_update_run_followup_rejects_non_list_messages(client):
    """messages must be a list."""
    r = client.patch(
        "/api/runs/some-run-id/followup",
        json={"agent_name": "x", "messages": "not-a-list"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── POST /api/workflows (already uses CreateWorkflowRequest) ──────────────
# Verify the handler uses a typed body param so OpenAPI is correct.


def test_create_workflow_rejects_missing_required(client):
    """POST /api/workflows with missing 'name' should 422."""
    r = client.post(
        "/api/workflows",
        json={"workflow": "x", "agents": []},  # missing name
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


def test_create_workflow_rejects_wrong_type_agents(client):
    """agents must be a list, not a string."""
    r = client.post(
        "/api/workflows",
        json={"name": "x", "workflow": "y", "agents": "not-a-list"},
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"


# ── POST /api/batch (already uses CreateBatchRequest) ─────────────────────


def test_create_batch_rejects_missing_required(client):
    """POST /api/batch with missing 'items' should 422."""
    r = client.post(
        "/api/batch",
        json={"name": "x", "workflow": "y", "agents": []},  # missing items
        headers={"X-User-Id": "default"},
    )
    assert r.status_code == 422, f"Got {r.status_code}: {r.text}"
