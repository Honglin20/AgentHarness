"""Phase C — ClaudeCodeExecutor 单元测试（mock subprocess，不调真 claude）。

e2e 测试（真实跑 claude）在 test_claude_code_executor_e2e.py，标 @pytest.mark.slow。

验收锚点（对应 detailed-design.md §6.5）：
  1. run() 主流程：spawn → 翻译 → emit → 提取 result → 返回 AgentRunResult
  2. emit text_delta / tool_call / tool_result；跳过 node.started/completed/failed
  3. result.result 文本提取正确
  4. usage 累计 + get_last_request_usage
  5. exit_code != 0 → RuntimeError
  6. 缺 result 事件 → RuntimeError
"""
from __future__ import annotations

import asyncio
import json
from typing import Sequence

import pytest

from harness.engine.claude_code_executor import (
    ClaudeCodeExecutor,
    _ClaudeAgentRun,
    _ClaudeResult,
    _ClaudeUsage,
)
from harness.engine.llm_executor import AgentRunResult, BaseExecutor
from harness.engine.cli_profile import CliRunResult, CliSpawnConfig


# ---------------------------------------------------------------------------
# Test fixtures / fakes
# ---------------------------------------------------------------------------


class FakeBus:
    """记录所有 emit 调用，方便断言事件序列。"""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict, **kwargs) -> None:
        self.events.append((event_type, payload))


def make_fake_run_claude(lines: Sequence[str], *, exit_code: int = 0, stderr: str = "", timed_out: bool = False):
    """构造一个 fake run_claude：按行触发 on_line callback，然后返回指定 exit_code。"""
    async def fake(cfg: CliSpawnConfig, profile=None, on_line=None, *, timeout=None):
        assert isinstance(cfg, CliSpawnConfig)
        if on_line is not None:
            for line in lines:
                await on_line(line)
        return CliRunResult(exit_code=exit_code, stderr=stderr, timed_out=timed_out)
    return fake


def make_executor(bus=None, agent_def=None, deps=None, **kwargs) -> ClaudeCodeExecutor:
    return ClaudeCodeExecutor(
        agent_def=agent_def,
        deps=deps,
        event_bus=bus,
        workflow_id="wf-1",
        node_id="node-1",
        agent_name="agent-1",
        **kwargs,
    )


def _run(coro):
    """跑 coro 在新 event loop，跑完 close 但**不**动 thread state。

    不能用 ``asyncio.run()`` —— 它会 ``set_event_loop(None)`` 把
    ``_local._set_called`` 标记为 True，导致后续测试的
    ``asyncio.get_event_loop()`` 不再 auto-create 而抛 RuntimeError
    （见 test_macro_graph.py::test_stop_regen_signal_ttl_expiry）。

    new_event_loop() 不会污染 thread state（不调 set_event_loop），
    close() 也不会；所以这条路径最干净。
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# 真实样本（Phase B fixture 提取出来的几行简化版）
SAMPLE_LINES_SUCCESS = [
    json.dumps({"type": "system", "subtype": "init", "session_id": "s1", "tools": ["Bash"]}),
    json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}}),
    json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "think..."}}}),
    json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "call_1", "name": "Bash", "input": {"command": "echo hi"}},
    ]}}),
    json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "call_1", "content": "hi"},
    ]}}),
    json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "duration_ms": 1234, "num_turns": 1, "result": "DONE",
        "total_cost_usd": 0.042,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50},
        "ttft_ms": 500,
    }),
]


# ---------------------------------------------------------------------------
# Shim dataclasses
# ---------------------------------------------------------------------------


class TestShims:
    def test_claude_usage_total_tokens(self):
        u = _ClaudeUsage(input_tokens=100, output_tokens=20)
        assert u.total_tokens == 120

    def test_claude_usage_defaults(self):
        u = _ClaudeUsage()
        assert u.total_tokens == 0
        assert u.requests == 1
        assert u.tool_calls == 0

    def test_claude_agent_run_default_lists(self):
        ar = _ClaudeAgentRun(result=_ClaudeResult(output="x"), usage=_ClaudeUsage())
        assert ar.new_messages == []
        assert ar.all_messages == []
        assert ar.metadata == {}


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_satisfies_base_executor_protocol(self):
        ex = make_executor()
        assert isinstance(ex, BaseExecutor)
        assert hasattr(ex, "run")
        assert hasattr(ex, "record_usage")
        assert hasattr(ex, "get_last_request_usage")
        assert hasattr(ex, "tool_calls")


# ---------------------------------------------------------------------------
# run() 主流程（mock run_claude）
# ---------------------------------------------------------------------------


class TestRunBasicFlow:
    def test_run_returns_agent_run_result_with_extracted_text(self, monkeypatch):
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        bus = FakeBus()
        ex = make_executor(bus=bus)
        result = _run(ex.run("do thing"))
        assert isinstance(result, AgentRunResult)
        assert result.agent_run.result.output == "DONE"
        assert result.ttft_ms == 500

    def test_run_emits_text_delta_to_bus(self, monkeypatch):
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        bus = FakeBus()
        ex = make_executor(bus=bus)
        _run(ex.run("do thing"))

        text_deltas = [e for e in bus.events if e[0] == "agent.text_delta"]
        assert len(text_deltas) == 1
        assert text_deltas[0][1]["text"] == "hello"
        # 路由字段正确
        assert text_deltas[0][1]["node_id"] == "node-1"
        assert text_deltas[0][1]["agent_name"] == "agent-1"
        assert text_deltas[0][1]["workflow_id"] == "wf-1"  # 由 _emit 注入

    def test_run_emits_thinking_delta(self, monkeypatch):
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        bus = FakeBus()
        ex = make_executor(bus=bus)
        _run(ex.run("do thing"))

        thinking = [e for e in bus.events if e[0] == "agent.thinking_delta"]
        assert len(thinking) == 1
        assert thinking[0][1]["text"] == "think..."

    def test_run_emits_tool_call_and_result(self, monkeypatch):
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        bus = FakeBus()
        ex = make_executor(bus=bus)
        _run(ex.run("do thing"))

        calls = [e for e in bus.events if e[0] == "agent.tool_call"]
        results = [e for e in bus.events if e[0] == "agent.tool_result"]
        assert len(calls) == 1
        assert len(results) == 1
        assert calls[0][1]["tool_name"] == "Bash"
        assert calls[0][1]["tool_args"] == {"command": "echo hi"}
        assert calls[0][1]["tool_call_id"] == "call_1"
        assert results[0][1]["result"] == "hi"
        assert results[0][1]["tool_call_id"] == "call_1"

    def test_run_does_not_emit_lifecycle_events(self, monkeypatch):
        """node_factory 自己 emit node.started/completed/failed；executor 不能重复。"""
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        bus = FakeBus()
        ex = make_executor(bus=bus)
        _run(ex.run("do thing"))

        types_emitted = {t for t, _ in bus.events}
        assert "node.started" not in types_emitted
        assert "node.completed" not in types_emitted
        assert "node.failed" not in types_emitted


class TestRunUsageTracking:
    def test_cumulative_usage_extracted_from_result(self, monkeypatch):
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        ex = make_executor()
        result = _run(ex.run("do"))
        u = result.agent_run.usage
        assert u.input_tokens == 100
        assert u.output_tokens == 20
        assert u.cache_read_tokens == 50
        assert u.total_tokens == 120

    def test_get_last_request_usage_after_run(self, monkeypatch):
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        ex = make_executor()
        _run(ex.run("do"))
        last = ex.get_last_request_usage()
        assert last == {"last_input": 100, "last_output": 20, "last_cache_hit": 50}

    def test_record_usage_is_noop_does_not_throw(self):
        ex = make_executor()
        # 任何对象传进去都不应抛
        ex.record_usage({"arbitrary": "obj"})
        ex.record_usage(None)

    def test_tool_calls_tracked_for_emit_metadata(self, monkeypatch):
        """node_factory 后续会读 executor.tool_calls 挂到 ext_ctx.metadata。"""
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        ex = make_executor()
        _run(ex.run("do"))
        assert len(ex.tool_calls) == 1
        assert ex.tool_calls[0]["tool_name"] == "Bash"
        assert ex.tool_calls[0]["tool_call_id"] == "call_1"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestRunErrorPaths:
    def test_nonzero_exit_raises_runtime_error(self, monkeypatch):
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude([], exit_code=1, stderr="boom"),
        )
        ex = make_executor()
        with pytest.raises(RuntimeError, match=r"claude subprocess exited code=1"):
            _run(ex.run("do"))

    def test_no_result_event_raises_runtime_error(self, monkeypatch):
        """claude exit=0 但没 emit result —— 异常情况，要 fail-loud。"""
        no_result_lines = [
            json.dumps({"type": "system", "subtype": "init", "tools": []}),
            json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "hi"}}}),
        ]
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(no_result_lines, exit_code=0),
        )
        ex = make_executor()
        with pytest.raises(RuntimeError, match=r"emitted no result event"):
            _run(ex.run("do"))

    def test_non_json_lines_ignored_not_crash(self, monkeypatch):
        """stdout 含非 JSON 行（不应发生，但要防御）。"""
        mixed_lines = [
            "this is not json",
            json.dumps({"type": "result", "is_error": False, "duration_ms": 1, "result": "ok"}),
        ]
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(mixed_lines),
        )
        ex = make_executor()
        result = _run(ex.run("do"))
        assert result.agent_run.result.output == "ok"

    def test_translate_callback_exception_does_not_crash_run(self, monkeypatch):
        """翻译 callback 内部抛错，run() 仍要正常完成（subprocess helper 兜底）。"""
        # on_line 在 _cli_subprocess 内部已经 try/except；这里间接验证
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        ex = make_executor()
        result = _run(ex.run("do"))
        assert result.agent_run.result.output == "DONE"


# ---------------------------------------------------------------------------
# Spawn config construction
# ---------------------------------------------------------------------------


class TestSpawnConfigConstruction:
    def _flag_value(self, cfg, flag):
        """Get the value following a --flag in cfg.extra_args, or None."""
        args = list(cfg.extra_args)
        if flag in args:
            return args[args.index(flag) + 1]
        return None

    def test_resolve_system_prompt_from_deps(self):
        class Deps:
            agent_md_content = "AGENT_MD_BODY"
        ex = make_executor(deps=Deps())
        cfg = ex._build_spawn_config("ctx")
        # System prompt lands in extra_args as `--append-system-prompt <body>`
        assert self._flag_value(cfg, "--append-system-prompt") == "AGENT_MD_BODY"
        assert cfg.prompt == "ctx"

    def test_resolve_system_prompt_from_agent_def(self):
        class AgentDef:
            prompt = "AGENT_DEF_PROMPT"
        ex = make_executor(agent_def=AgentDef())
        cfg = ex._build_spawn_config("ctx")
        assert self._flag_value(cfg, "--append-system-prompt") == "AGENT_DEF_PROMPT"

    def test_resolve_system_prompt_none_when_no_source(self):
        ex = make_executor()
        cfg = ex._build_spawn_config("ctx")
        # No system prompt → --append-system-prompt absent
        assert "--append-system-prompt" not in cfg.extra_args

    def test_resolve_allowed_tools_from_agent_def(self):
        class AgentDef:
            tools = ["Bash", "Read"]
        ex = make_executor(agent_def=AgentDef())
        cfg = ex._build_spawn_config("ctx")
        # Allowed tools space-joined into a single --allowed-tools arg (Phase 1 V1 lesson)
        assert self._flag_value(cfg, "--allowed-tools") == "Bash Read"

    def test_resolve_allowed_tools_none_when_unset(self):
        class AgentDef:
            tools = None
        ex = make_executor(agent_def=AgentDef())
        cfg = ex._build_spawn_config("ctx")
        # No tools → --allowed-tools absent
        assert "--allowed-tools" not in cfg.extra_args

    def test_mcp_config_path_forwarded(self):
        ex = make_executor(mcp_config_path="/tmp/mcp.json")
        cfg = ex._build_spawn_config("ctx")
        # MCP path rendered via profile.build_mcp_flag_args → mcp_flag_args tuple
        assert "--mcp-config" in cfg.mcp_flag_args
        assert "/tmp/mcp.json" in cfg.mcp_flag_args


# ---------------------------------------------------------------------------
# run() state reset between calls
# ---------------------------------------------------------------------------


class TestStateResetBetweenRuns:
    def test_tool_calls_reset_between_runs(self, monkeypatch):
        """如果同一个 executor 实例被重试逻辑复用（不太可能，但要稳健），per-run state 必须重置。"""
        monkeypatch.setattr(
            "harness.engine.claude_code_executor.run_cli",
            make_fake_run_claude(SAMPLE_LINES_SUCCESS),
        )
        ex = make_executor()
        _run(ex.run("first"))
        assert len(ex.tool_calls) == 1
        _run(ex.run("second"))
        # 第二次 run 不应该把第一次的 tool_calls 累加
        assert len(ex.tool_calls) == 1
