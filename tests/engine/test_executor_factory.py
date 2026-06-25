"""Phase A — make_executor 工厂分派单元测试。

验收锚点（对应 detailed-design.md §4.3）：
  1. ``executor=="pydantic-ai"`` → LLMExecutor
  2. ``executor=="claude-code"``  → ClaudeCodeExecutor
  3. 缺省（getattr fallback）→ LLMExecutor
  4. 未知 backend → ValueError
  5. 两个 executor 都满足 BaseExecutor 协议
"""
from __future__ import annotations

import pytest

from harness.core.agent import Agent
from harness.engine.executor_factory import make_executor
from harness.engine.llm_executor import BaseExecutor, LLMExecutor
from harness.engine.claude_code_executor import ClaudeCodeExecutor


class _DummyPydanticAgent:
    """占位 —— LLMExecutor 实例化不需要真实 pydantic-ai Agent。"""


class TestMakeExecutorDispatch:
    def test_pydantic_ai_dispatches_to_llm_executor(self):
        a = Agent("p", executor="pydantic-ai")
        ex = make_executor(
            agent_def=a,
            pydantic_agent=_DummyPydanticAgent(),
            deps=None,
            agent_name="p",
        )
        assert isinstance(ex, LLMExecutor)
        assert isinstance(ex, BaseExecutor)

    def test_claude_code_dispatches_to_claude_code_executor(self):
        a = Agent("c", executor="claude-code")
        ex = make_executor(
            agent_def=a,
            pydantic_agent=_DummyPydanticAgent(),
            deps=None,
            agent_name="c",
        )
        assert isinstance(ex, ClaudeCodeExecutor)
        assert isinstance(ex, BaseExecutor)

    def test_default_agent_dispatches_to_llm_executor(self):
        """没显式声明 executor 字段的 Agent 走 pydantic-ai 路径。"""
        a = Agent("d")
        ex = make_executor(
            agent_def=a,
            pydantic_agent=_DummyPydanticAgent(),
            deps=None,
            agent_name="d",
        )
        assert isinstance(ex, LLMExecutor)

    def test_duck_typed_agent_def_works_via_getattr(self):
        """agent_def 不必是 Agent 实例，只要有 ``executor`` 属性即可（前向兼容）。"""
        class FakeAgent:
            executor = "claude-code"

        ex = make_executor(
            agent_def=FakeAgent(),
            pydantic_agent=None,
            deps=None,
            agent_name="fake",
        )
        assert isinstance(ex, ClaudeCodeExecutor)

    def test_getattr_fallback_when_attr_missing(self):
        """agent_def 完全没 executor 属性时回落到 pydantic-ai（兼容老代码路径）。"""
        class LegacyAgent:
            pass  # 无 executor 属性

        ex = make_executor(
            agent_def=LegacyAgent(),
            pydantic_agent=_DummyPydanticAgent(),
            deps=None,
            agent_name="legacy",
        )
        assert isinstance(ex, LLMExecutor)


class TestMakeExecutorProtocolConformance:
    def test_llm_executor_satisfies_base_executor_protocol(self):
        """LLMExecutor 是历史代码，必须天然满足 BaseExecutor —— 0 行为变更。"""
        a = Agent("p")
        ex = make_executor(
            agent_def=a,
            pydantic_agent=_DummyPydanticAgent(),
            deps=None,
            agent_name="p",
        )
        # runtime_checkable Protocol —— 检查方法/属性存在
        assert isinstance(ex, BaseExecutor)
        assert hasattr(ex, "run")
        assert hasattr(ex, "record_usage")
        assert hasattr(ex, "get_last_request_usage")
        assert hasattr(ex, "tool_calls")

    def test_claude_code_executor_satisfies_base_executor_protocol(self):
        a = Agent("c", executor="claude-code")
        ex = make_executor(
            agent_def=a,
            pydantic_agent=None,
            deps=None,
            agent_name="c",
        )
        assert isinstance(ex, BaseExecutor)
        assert hasattr(ex, "run")
        assert hasattr(ex, "record_usage")
        assert hasattr(ex, "get_last_request_usage")
        assert hasattr(ex, "tool_calls")
        assert ex.tool_calls == []  # 初始化为空 list

    def test_claude_code_executor_run_is_fail_loud(self):
        """Phase A 占位：调 run() 必须明确 NotImplementedError，不能悄悄 fallback。

        Note: 不能用 ``asyncio.run()`` —— 它会关闭并清除当前线程的 event loop,
        污染后续测试的 ``asyncio.get_event_loop()`` 调用（见
        test_macro_graph.py::test_stop_regen_signal_ttl_expiry）。
        用 ``asyncio.new_event_loop()`` 显式管理，跑完只 close 不污染 thread state。
        """
        import asyncio
        a = Agent("c", executor="claude-code")
        ex = make_executor(
            agent_def=a,
            pydantic_agent=None,
            deps=None,
            agent_name="c",
        )
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(NotImplementedError, match=r"Phase C"):
                loop.run_until_complete(ex.run("hello"))
        finally:
            loop.close()


class TestMakeExecutorForwarding:
    """工厂必须把所有 metadata 参数透传给底层 executor（不能丢字段）。"""

    def test_metadata_reaches_claude_code_executor(self):
        a = Agent("c", executor="claude-code")
        ex = make_executor(
            agent_def=a,
            pydantic_agent=None,
            deps="DEPS",
            event_bus="BUS",
            workflow_id="wf-1",
            node_id="node-1",
            agent_name="agent-1",
            ext_ctx="EXT",
            request_limit=42,
        )
        assert ex.agent_def is a
        assert ex._deps == "DEPS"
        assert ex._bus == "BUS"
        assert ex._wid == "wf-1"
        assert ex._node_id == "node-1"
        assert ex._agent_name == "agent-1"
        assert ex._ext_ctx == "EXT"
        assert ex._request_limit == 42
