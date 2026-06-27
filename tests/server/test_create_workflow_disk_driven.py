"""Disk-driven POST /api/workflows — workflow.json 是 agents 真相源。

验收锚点：
  1. workflow.json 存在 → agents 完全用盘上定义（含 PATCH 写入的 executor）
  2. POST body 的 agents 字段在盘存在时被忽略（盘优先，不被覆盖）
  3. ad-hoc（无 workflow.json）→ fallback 到 POST body 的 agents
  4. ad-hoc 无 POST body agents → fail loud（400）
  5. _build_agents_snapshot 写 executor + _reconstruct_run_to_repo 读 executor
     （resume / 进程重启后 executor 不丢）
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wf_root(tmp_path: Path) -> Path:
    """临时 workflows/ 目录。"""
    return tmp_path


@pytest.fixture
def wf_with_executor(wf_root: Path) -> Path:
    """workflow.json 含 agent_claude (executor=claude-code) + agent_pydantic (默认)."""
    wf_dir = wf_root / "test_wf"
    wf_dir.mkdir()
    (wf_dir / "agents").mkdir()
    (wf_dir / "workflow.json").write_text(json.dumps({
        "name": "test_wf",
        "agents": [
            {"name": "agent_claude", "after": [], "executor": "claude-code"},
            {"name": "agent_pydantic", "after": ["agent_claude"]},
        ],
        "max_iterations": 3,
    }))
    return wf_root


def _make_fake_checkpoint_mgr():
    """Fake checkpointer manager — get_checkpointer 返回 None（workflow 不持久化）。"""
    mgr = MagicMock()
    mgr.get_checkpointer = AsyncMock(return_value=None)
    return mgr


def _make_fake_runner():
    """Fake runner — submit no-op（不真正跑 workflow）。"""
    runner = MagicMock()
    runner.submit = AsyncMock(return_value=None)
    return runner


async def _invoke_create(agents_defs, workflow_name, wf_root: Path, user_id=None):
    """调用 _create_and_start_workflow，mock 掉 runner/checkpointer/repo。

    Returns: (workflow_obj, dag) — workflow 来自 repo.put 时的引用。
    """
    from server._helpers import _create_and_start_workflow
    from server.repository import get_repository

    captured_workflows: list = []

    repo = get_repository()
    orig_put = repo.put

    def capture_put(wf_id, data):
        captured_workflows.append(data.get("workflow"))
        return orig_put(wf_id, data)

    repo.put = capture_put

    with patch("harness.core.workflow._WORKFLOWS_DIR", wf_root), \
         patch("harness.workflow._WORKFLOWS_DIR", wf_root), \
         patch("harness.checkpoint.get_checkpoint_manager", return_value=_make_fake_checkpoint_mgr()), \
         patch("server.runner.get_runner", return_value=_make_fake_runner()):
        result = await _create_and_start_workflow(
            name=workflow_name,
            agents_defs=agents_defs,
            workflow_name=workflow_name,
            inputs={"task": "test"},
            user_id=user_id,
        )

    assert len(captured_workflows) == 1, f"Expected 1 workflow captured, got {len(captured_workflows)}"
    return captured_workflows[0], result.dag


# ---------------------------------------------------------------------------
# 盘驱动主路径
# ---------------------------------------------------------------------------


async def test_disk_driven_uses_workflow_json_executor(wf_with_executor: Path):
    """workflow.json 有 executor=claude-code，POST body agents=None → 用盘。"""
    workflow, _ = await _invoke_create(
        agents_defs=None,
        workflow_name="test_wf",
        wf_root=wf_with_executor,
    )

    agents_by_name = {a.name: a for a in workflow.agents}
    assert agents_by_name["agent_claude"].executor == "claude-code"
    assert agents_by_name["agent_pydantic"].executor == "pydantic-ai"


async def test_disk_driven_ignores_post_body_agents(wf_with_executor: Path):
    """盘存在时 POST body 的 agents 被完全忽略（不被覆盖）。

    Regression: 旧逻辑 base.update({"executor": a.executor}) 让 POST body
    默认值 "pydantic-ai" 覆盖盘上 "claude-code"，导致 executor 丢失。
    """
    from server.schemas import AgentDef

    # POST body 故意传 executor=pydantic-ai（试图覆盖盘上的 claude-code）
    post_body_agents = [
        AgentDef(name="agent_claude", after=[], executor="pydantic-ai"),
        AgentDef(name="agent_pydantic", after=["agent_claude"]),
    ]

    workflow, _ = await _invoke_create(
        agents_defs=post_body_agents,
        workflow_name="test_wf",
        wf_root=wf_with_executor,
    )

    agents_by_name = {a.name: a for a in workflow.agents}
    # 盘优先：POST body 的 pydantic-ai 不应覆盖盘上的 claude-code
    assert agents_by_name["agent_claude"].executor == "claude-code", \
        "POST body must NOT override disk workflow.json executor"


# ---------------------------------------------------------------------------
# Ad-hoc fallback
# ---------------------------------------------------------------------------


async def test_ad_hoc_fallback_uses_post_body(wf_root: Path):
    """无 workflow.json（ad-hoc）→ fallback 到 POST body agents。"""
    from server.schemas import AgentDef

    # 不创建 workflow.json；workflow_name 用一个不存在的目录
    post_body_agents = [
        AgentDef(name="scout", after=[], executor="claude-code"),
        AgentDef(name="reporter", after=["scout"]),
    ]

    workflow, _ = await _invoke_create(
        agents_defs=post_body_agents,
        workflow_name="adhoc_chain",
        wf_root=wf_root,
    )

    agents_by_name = {a.name: a for a in workflow.agents}
    assert agents_by_name["scout"].executor == "claude-code"
    assert agents_by_name["reporter"].executor == "pydantic-ai"


async def test_ad_hoc_without_agents_fails_loud(wf_root: Path):
    """无 workflow.json + 无 POST body agents → 400（fail loud）。"""
    from fastapi import HTTPException
    from server._helpers import _create_and_start_workflow

    with patch("harness.core.workflow._WORKFLOWS_DIR", wf_root), \
         patch("harness.workflow._WORKFLOWS_DIR", wf_root), \
         patch("harness.checkpoint.get_checkpoint_manager", return_value=_make_fake_checkpoint_mgr()), \
         patch("server.runner.get_runner", return_value=_make_fake_runner()):
        with pytest.raises(HTTPException) as exc_info:
            await _create_and_start_workflow(
                name="no_wf_no_agents",
                agents_defs=None,
                workflow_name="no_wf_no_agents",
                inputs={"task": "x"},
            )

    assert exc_info.value.status_code == 400
    assert "no workflow.json" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Resume 链路：snapshot + reconstruct 保 executor
# ---------------------------------------------------------------------------


def test_build_agents_snapshot_writes_executor_when_non_default():
    """非默认 executor 写入 snapshot；默认值不写（与 Agent.to_dict 一致）。"""
    from harness.core.agent import Agent
    from server.runner import _build_agents_snapshot

    agent_claude = Agent(name="claude_agent", executor="claude-code")
    agent_pydantic = Agent(name="pydantic_agent")

    class FakeWorkflow:
        agents = [agent_claude, agent_pydantic]
        workflow_dir = Path("/tmp/fake")

    snapshot = _build_agents_snapshot(FakeWorkflow())
    snap_by_name = {s["name"]: s for s in snapshot}

    assert snap_by_name["claude_agent"].get("executor") == "claude-code", \
        "Non-default executor must be written to snapshot"
    assert "executor" not in snap_by_name["pydantic_agent"], \
        "Default executor must NOT be written (avoid disk diff)"


def test_reconstruct_run_to_repo_preserves_executor(wf_root: Path, monkeypatch):
    """snapshot 带 executor → reconstruct 后 agent.executor 正确恢复。"""
    import os
    from datetime import datetime, timezone

    from fastapi import Request
    from server._helpers import _reconstruct_run_to_repo
    from server.repository import get_repository

    # 一个简单的 ad-hoc workflow 目录（_reconstruct 不读 workflow.json 的 agents）
    wf_dir = wf_root / "resume_wf"
    wf_dir.mkdir()
    (wf_dir / "agents").mkdir()
    (wf_dir / "workflow.json").write_text(json.dumps({
        "name": "resume_wf",
        "agents": [],
    }))

    monkeypatch.setattr("harness.core.workflow._WORKFLOWS_DIR", wf_root)

    class FakeUser:
        user_id = "default"

    class FakeUserMgr:
        def is_admin(self, _u):
            return True

    fake_request = MagicMock(spec=Request)

    record = {
        "workflow_name": "resume_wf",
        "user_id": "default",
        "work_dir": None,
        "result": None,
        "inputs": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dag": {"nodes": ["agent_claude"], "edges": [], "conditional_edges": []},
        "agents_snapshot": [
            {
                "name": "agent_claude",
                "after": [],
                "executor": "claude-code",
                "retries": 3,
            },
        ],
    }

    repo = get_repository()
    with patch("server._helpers.get_current_user", return_value=FakeUser()), \
         patch("server._helpers.get_user_manager", return_value=FakeUserMgr()):
        _reconstruct_run_to_repo(repo, "run-x", record, fake_request)

    data = repo.get("run-x")
    workflow = data["workflow"]
    assert workflow.agents[0].executor == "claude-code", \
        "Reconstructed agent must preserve executor from snapshot"
