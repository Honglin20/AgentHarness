"""Phase E — ClaudeCodeExecutor 集成 schema 校验测试。

验证 ClaudeCodeExecutor._extract_and_validate_result 在 run() 主流程里的行为。
"""
from __future__ import annotations

import asyncio
import json
from typing import Sequence

import pytest
from pydantic import BaseModel

from harness.core.agent import Agent
from harness.engine.cli_profile import CliRunResult, CliSpawnConfig
from harness.engine._result_extractor import SchemaValidationError
from harness.engine.claude_code_executor import ClaudeCodeExecutor
from harness.engine.error_event import ExecutorError
from harness.types import AgentResult


class _Summary(BaseModel):
    """自定义 result_type 测试用。"""
    summary: str
    count: int


class FakeBus:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, **kwargs) -> None:
        self.events.append((event_type, payload))


def make_fake_run_claude(lines: Sequence[str], *, exit_code: int = 0):
    async def fake(cfg: CliSpawnConfig, profile=None, on_line=None, *, timeout=None):
        if on_line is not None:
            for line in lines:
                await on_line(line)
        return CliRunResult(exit_code=exit_code, stderr="", timed_out=False)
    return fake


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# result_type = AgentResult (默认) — text 包成 AgentResult
# ---------------------------------------------------------------------------


class TestDefaultResultTypeAgentResult:
    def test_text_wrapped_as_agent_result(self, monkeypatch):
        """agent_def.result_type=AgentResult（默认）→ text 包成 AgentResult(summary=...)。"""
        lines = [
            json.dumps({"type": "result", "is_error": False, "duration_ms": 100,
                        "result": "hello world", "usage": {}}),
        ]
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(lines),
        )
        ex = ClaudeCodeExecutor(
            agent_def=Agent("a"),  # default result_type=AgentResult
            deps=None, workflow_id="w", node_id="n", agent_name="a",
            enable_mcp=False,
        )
        result = _run(ex.run("ctx"))
        assert isinstance(result.agent_run.result.output, AgentResult)
        assert result.agent_run.result.output.summary == "hello world"


# ---------------------------------------------------------------------------
# result_type = None — free text
# ---------------------------------------------------------------------------


class TestResultTypeNone:
    def test_agent_def_none_returns_text_directly(self, monkeypatch):
        """agent_def=None → free text 直接返回（不包 AgentResult）。"""
        lines = [
            json.dumps({"type": "result", "is_error": False, "duration_ms": 100,
                        "result": "free text", "usage": {}}),
        ]
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(lines),
        )
        ex = ClaudeCodeExecutor(
            agent_def=None,  # 关键：no agent_def
            deps=None, workflow_id="w", node_id="n", agent_name="a",
            enable_mcp=False,
        )
        result = _run(ex.run("ctx"))
        assert result.agent_run.result.output == "free text"


# ---------------------------------------------------------------------------
# result_type = custom BaseModel — 严格 JSON + schema 校验
# ---------------------------------------------------------------------------


class TestCustomResultType:
    def test_valid_json_returns_validated_instance(self, monkeypatch):
        lines = [
            json.dumps({"type": "result", "is_error": False, "duration_ms": 100,
                        "result": '{"summary": "ok", "count": 42}',
                        "usage": {}}),
        ]
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(lines),
        )
        agent_def = Agent("a", result_type=_Summary)
        ex = ClaudeCodeExecutor(
            agent_def=agent_def,
            deps=None, workflow_id="w", node_id="n", agent_name="a",
            enable_mcp=False,
        )
        result = _run(ex.run("ctx"))
        assert isinstance(result.agent_run.result.output, _Summary)
        assert result.agent_run.result.output.summary == "ok"
        assert result.agent_run.result.output.count == 42

    def test_json_in_fence_validates(self, monkeypatch):
        lines = [
            json.dumps({"type": "result", "is_error": False, "duration_ms": 100,
                        "result": 'Here:\n```json\n{"summary": "x", "count": 1}\n```\nDone.',
                        "usage": {}}),
        ]
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(lines),
        )
        agent_def = Agent("a", result_type=_Summary)
        ex = ClaudeCodeExecutor(
            agent_def=agent_def,
            deps=None, workflow_id="w", node_id="n", agent_name="a",
            enable_mcp=False,
        )
        result = _run(ex.run("ctx"))
        assert isinstance(result.agent_run.result.output, _Summary)

    def test_invalid_schema_raises_validation_error(self, monkeypatch):
        """schema 不匹配 → SchemaValidationError 被 P2-T3 包装为
        ExecutorError(phase=schema_validate)，execute_with_retry 见
        ExecutorError 走 retry 但不重 emit (emit-uniqueness 契约)。"""
        lines = [
            json.dumps({"type": "result", "is_error": False, "duration_ms": 100,
                        "result": '{"summary": "x"}',  # missing count
                        "usage": {}}),
        ]
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(lines),
        )
        agent_def = Agent("a", result_type=_Summary)
        ex = ClaudeCodeExecutor(
            agent_def=agent_def,
            deps=None, workflow_id="w", node_id="n", agent_name="a",
            enable_mcp=False,
        )
        with pytest.raises(ExecutorError) as exc_info:
            _run(ex.run("ctx"))
        err = exc_info.value
        assert err.error_event.phase == "schema_validate"
        assert err.error_event.error_type == "SchemaValidationError"
        assert "schema validation failed" in err.error_event.error_message

    def test_invalid_json_raises_validation_error(self, monkeypatch):
        """纯文本（无 JSON）+ custom result_type → 提取失败。"""
        lines = [
            json.dumps({"type": "result", "is_error": False, "duration_ms": 100,
                        "result": 'just plain text',
                        "usage": {}}),
        ]
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(lines),
        )
        agent_def = Agent("a", result_type=_Summary)
        ex = ClaudeCodeExecutor(
            agent_def=agent_def,
            deps=None, workflow_id="w", node_id="n", agent_name="a",
            enable_mcp=False,
        )
        with pytest.raises(ExecutorError) as exc_info:
            _run(ex.run("ctx"))
        err = exc_info.value
        assert err.error_event.phase == "schema_validate"
        assert "no JSON candidate" in err.error_event.error_message
