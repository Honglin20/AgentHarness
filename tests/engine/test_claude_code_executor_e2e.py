"""Phase C — ClaudeCodeExecutor e2e 测试（真实跑 claude -p）。

标 ``@pytest.mark.slow``，默认 deselected（pyproject.toml addopts="-m 'not slow'"）。
要跑：``pytest tests/engine/test_claude_code_executor_e2e.py -m slow``

如果环境里没 claude CLI 在 PATH，自动 skip。

验收锚点（对应 detailed-design.md §6.5 e2e）：
  1. 简单 prompt → result.output 含期望文本
  2. bash 工具 prompt → tool_calls 非空 + result.output 含命令输出
  3. usage 累计字段（input/output）非零
"""
from __future__ import annotations

import asyncio
import shutil
import sys

import pytest

from harness.engine.claude_code_executor import ClaudeCodeExecutor


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        shutil.which("claude") is None,
        reason="claude CLI not in PATH; cannot run e2e",
    ),
]


class FakeBus:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, **kwargs) -> None:
        self.events.append((event_type, payload))


def _run(coro):
    """跑 async 测试，避免污染 thread state（见 Phase A 教训）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_executor(bus=None) -> ClaudeCodeExecutor:
    return ClaudeCodeExecutor(
        agent_def=None,
        deps=None,
        event_bus=bus,
        workflow_id="wf-e2e",
        node_id="node-e2e",
        agent_name="agent-e2e",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestE2ESimplePrompt:
    def test_simple_prompt_returns_expected_text(self):
        ex = _make_executor()
        result = _run(ex.run('Reply with exactly one word: PONG. Nothing else.'))
        assert "PONG" in str(result.agent_run.result.output)

    def test_simple_prompt_emits_text_delta(self):
        bus = FakeBus()
        ex = _make_executor(bus=bus)
        _run(ex.run('Reply with exactly one word: PONG. Nothing else.'))
        text_deltas = [e for e in bus.events if e[0] == "agent.text_delta"]
        assert len(text_deltas) >= 1
        combined = "".join(d[1]["text"] for d in text_deltas)
        assert "PONG" in combined

    def test_simple_prompt_no_tool_calls(self):
        ex = _make_executor()
        _run(ex.run('Reply with exactly one word: PONG. Nothing else.'))
        assert ex.tool_calls == []

    def test_simple_prompt_usage_nonzero(self):
        ex = _make_executor()
        result = _run(ex.run('Reply with exactly one word: PONG. Nothing else.'))
        u = result.agent_run.usage
        assert u.input_tokens > 0
        assert u.output_tokens > 0


class TestE2EBashTool:
    def test_bash_prompt_records_tool_call(self):
        """让 claude 用 Bash 工具跑 echo，验证 tool_calls 累计 + result 含输出。"""
        ex = _make_executor()
        # 不传 allowed_tools 让 claude 自选工具集
        result = _run(ex.run(
            'Use the Bash tool to run the command `echo E2E_BASH_TEST_42`, '
            'then reply with exactly the word DONE on its own line.'
        ))
        # 至少调了一次 Bash
        bash_calls = [tc for tc in ex.tool_calls if tc.get("tool_name") == "Bash"]
        assert len(bash_calls) >= 1, f"expected ≥1 Bash call, got {ex.tool_calls}"
        # result.output 含 DONE（claude 完成了任务）
        assert "DONE" in str(result.agent_run.result.output).upper() or \
               "E2E_BASH_TEST_42" in str(result.agent_run.result.output)

    def test_bash_prompt_emits_tool_call_and_result_events(self):
        bus = FakeBus()
        ex = _make_executor(bus=bus)
        _run(ex.run(
            'Use the Bash tool to run `echo EVENT_TEST`, '
            'then reply with the word DONE.'
        ))
        calls = [e for e in bus.events if e[0] == "agent.tool_call"]
        results = [e for e in bus.events if e[0] == "agent.tool_result"]
        assert len(calls) >= 1
        assert len(results) >= 1
        # tool_call_id 关联：每个 result 必须有对应的 call
        call_ids = {c[1]["tool_call_id"] for c in calls}
        for r in results:
            assert r[1]["tool_call_id"] in call_ids


class TestE2EErrorPath:
    def test_executor_runs_without_bus_does_not_crash(self):
        """没传 event_bus（None）时，run() 仍要正常工作（emit 跳过）。"""
        ex = _make_executor(bus=None)
        result = _run(ex.run('Reply with exactly one word: PONG. Nothing else.'))
        assert "PONG" in str(result.agent_run.result.output)
