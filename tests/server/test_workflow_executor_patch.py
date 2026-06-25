"""Phase F.1 — PATCH /api/workflows/definitions/{name}/agents/{agent_name} 测试。

验收锚点（对应 detailed-design.md §9.6）:
  1. PATCH claude-code → workflow.json 写入 executor 字段
  2. PATCH pydantic-ai → workflow.json 移除 executor 字段（默认值不写盘）
  3. 其他 agent 不受影响
  4. 404 workflow 不存在 / agent 不存在
  5. 422 非法 executor 值（pydantic Literal 校验）
  6. atomic write（tmpfile + os.replace）— 中断后文件不半写
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def wf_root(tmp_path: Path) -> Path:
    """临时 workflows/ 目录，含一个 test_wf 工作流。"""
    wf_dir = tmp_path / "test_wf"
    wf_dir.mkdir()
    (wf_dir / "agents").mkdir()
    (wf_dir / "workflow.json").write_text(json.dumps({
        "name": "test_wf",
        "agents": [
            {"name": "agent_a", "after": [], "tools": [], "model": None, "retries": 3},
            {"name": "agent_b", "after": ["agent_a"], "tools": [], "model": None, "retries": 3},
        ],
        "max_iterations": 3,
    }))
    return tmp_path


@pytest.fixture
def client(wf_root: Path) -> TestClient:
    """构造 TestClient，monkeypatch workflows dir + 跳过权限校验。"""
    import harness.core.workflow as core_wf
    import harness.workflow as wf_mod
    import server.routers.workflows as wrt

    class FakeUser:
        user_id = "default"

    class FakeUserMgr:
        def can_delete_workflow(self, *args, **kw):
            return True

    def fake_get_user(req):
        return FakeUser()

    def fake_get_user_mgr():
        return FakeUserMgr()

    # patch workflows dir 必须在 import router 之前生效
    with patch.object(core_wf, "_WORKFLOWS_DIR", wf_root), \
         patch.object(wf_mod, "_WORKFLOWS_DIR", wf_root), \
         patch.object(wrt, "get_current_user", fake_get_user), \
         patch.object(wrt, "get_user_manager", fake_get_user_mgr):
        # router 已 import 过；直接 reuse
        from server.routers.workflows import router
        app = FastAPI()
        app.include_router(router, prefix="/api")
        # TestClient.__enter__ 激活 patch（patch 在 with 生命周期内）
        with TestClient(app) as c:
            yield c


def _read_workflow_json(wf_root: Path, name: str = "test_wf") -> dict:
    return json.loads((wf_root / name / "workflow.json").read_text())


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestPatchExecutorHappyPath:
    def test_patch_to_claude_code_writes_field(self, client, wf_root):
        r = client.patch(
            "/api/workflows/definitions/test_wf/agents/agent_a",
            json={"executor": "claude-code"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["executor"] == "claude-code"
        assert body["workflow"] == "test_wf"
        assert body["agent"] == "agent_a"

        # workflow.json 已更新
        data = _read_workflow_json(wf_root)
        agent_a = next(a for a in data["agents"] if a["name"] == "agent_a")
        assert agent_a["executor"] == "claude-code"

    def test_patch_to_pydantic_ai_removes_field(self, client, wf_root):
        # 先切到 claude-code
        client.patch(
            "/api/workflows/definitions/test_wf/agents/agent_a",
            json={"executor": "claude-code"},
        )
        # 再切回 pydantic-ai
        r = client.patch(
            "/api/workflows/definitions/test_wf/agents/agent_a",
            json={"executor": "pydantic-ai"},
        )
        assert r.status_code == 200

        data = _read_workflow_json(wf_root)
        agent_a = next(a for a in data["agents"] if a["name"] == "agent_a")
        # 默认值不写盘（与 Agent.to_dict 行为一致）
        assert "executor" not in agent_a

    def test_other_agents_untouched(self, client, wf_root):
        client.patch(
            "/api/workflows/definitions/test_wf/agents/agent_a",
            json={"executor": "claude-code"},
        )
        data = _read_workflow_json(wf_root)
        agent_b = next(a for a in data["agents"] if a["name"] == "agent_b")
        assert "executor" not in agent_b
        # agent_a 原有字段（after / retries / etc.）保留
        agent_a = next(a for a in data["agents"] if a["name"] == "agent_a")
        assert agent_a["after"] == []
        assert agent_a["retries"] == 3
        assert agent_a["tools"] == []

    def test_roundtrip_claude_code_then_pydantic_ai(self, client, wf_root):
        """切过去再切回来，workflow.json 字段状态正确。"""
        for expected in ("claude-code", "pydantic-ai", "claude-code", "pydantic-ai"):
            client.patch(
                "/api/workflows/definitions/test_wf/agents/agent_a",
                json={"executor": expected},
            )
            data = _read_workflow_json(wf_root)
            agent_a = next(a for a in data["agents"] if a["name"] == "agent_a")
            if expected == "claude-code":
                assert agent_a.get("executor") == "claude-code"
            else:
                assert "executor" not in agent_a


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestPatchExecutorErrors:
    def test_404_unknown_workflow(self, client):
        r = client.patch(
            "/api/workflows/definitions/nonexistent_wf/agents/agent_a",
            json={"executor": "claude-code"},
        )
        assert r.status_code == 404
        assert "nonexistent_wf" in r.json()["detail"]

    def test_404_unknown_agent(self, client):
        r = client.patch(
            "/api/workflows/definitions/test_wf/agents/nonexistent_agent",
            json={"executor": "claude-code"},
        )
        assert r.status_code == 404
        assert "nonexistent_agent" in r.json()["detail"]

    def test_422_invalid_executor_value(self, client):
        r = client.patch(
            "/api/workflows/definitions/test_wf/agents/agent_a",
            json={"executor": "invalid-backend"},
        )
        assert r.status_code == 422  # pydantic Literal validation

    def test_422_missing_executor_field(self, client):
        r = client.patch(
            "/api/workflows/definitions/test_wf/agents/agent_a",
            json={},
        )
        assert r.status_code == 422

    def test_422_wrong_field_type(self, client):
        """executor 字段必须是 string，不能是 int。"""
        r = client.patch(
            "/api/workflows/definitions/test_wf/agents/agent_a",
            json={"executor": 42},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Atomic write 验证
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_workflow_json_remains_valid_after_patch(self, client, wf_root):
        """连续多次 PATCH 后 workflow.json 仍是合法 JSON 且结构完整。"""
        for _ in range(5):
            client.patch(
                "/api/workflows/definitions/test_wf/agents/agent_a",
                json={"executor": "claude-code"},
            )
            client.patch(
                "/api/workflows/definitions/test_wf/agents/agent_a",
                json={"executor": "pydantic-ai"},
            )

        # 最终文件可正常 parse
        data = _read_workflow_json(wf_root)
        assert data["name"] == "test_wf"
        assert len(data["agents"]) == 2
        # 不应有 .tmp 文件残留
        wf_dir = wf_root / "test_wf"
        tmp_files = list(wf_dir.glob("*.tmp"))
        assert tmp_files == [], f"found stale tmp files: {tmp_files}"
