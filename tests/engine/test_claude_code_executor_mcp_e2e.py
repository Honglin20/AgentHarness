"""Phase D e2e — ClaudeCodeExecutor + harness MCP server 集成测试。

真实跑 claude -p，验证：
  - ClaudeCodeExecutor._setup_mcp 正确启动 proxy + 写 mcp-config
  - claude 通过 --mcp-config 连上 harness MCP server 子进程
  - claude 调 mcp__harness__ping → IPC → 主进程 handler → 回流 → claude 继续
  - 子进程结束 _teardown_mcp 清理 socket + 文件

@slow 标记；CI 默认 deselect；要跑：pytest -m slow tests/engine/test_claude_code_executor_mcp_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

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
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_executor(bus=None, **kwargs) -> ClaudeCodeExecutor:
    return ClaudeCodeExecutor(
        agent_def=None,
        deps=None,
        event_bus=bus,
        workflow_id="wf-mcp-e2e",
        node_id="node-mcp-e2e",
        agent_name="agent-mcp-e2e",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestE2EMcpPing:
    def test_claude_calls_harness_ping_via_mcp(self):
        """claude 通过 mcp__harness__ping 调主进程 handler，返回值回流到 claude。

        完整链路:
          claude --stdout stream-json--> ClaudeCodeExecutor._handle_stdout_line
                                          ↓ translate
                                          ↓ emit agent.tool_call / tool_result
                                          (claude 内部 JSON-RPC 流向 harness.mcp.server)
                                          ↓ socket
                                          McpProxyServer._dispatch → _ping_handler
                                          ↓ socket 回流
                                          (claude 收到 tool_result 继续)
        """
        bus = FakeBus()
        ex = _make_executor(bus=bus, enable_mcp=True)
        # 让 claude 调 ping 工具，传一个独特 marker
        prompt = (
            "Use the mcp__harness__ping tool to send the text 'E2E_MCP_MARKER'. "
            "After receiving the tool result, output exactly the word DONE on its own line."
        )
        result = _run(ex.run(prompt))

        # 1. claude 应该调了 mcp__harness__ping
        ping_calls = [
            e for e in bus.events
            if e[0] == "agent.tool_call" and e[1].get("tool_name") == "mcp__harness__ping"
        ]
        assert len(ping_calls) >= 1, f"expected ≥1 mcp__harness__ping call, got {bus.events}"
        assert ping_calls[0][1]["tool_args"].get("text") == "E2E_MCP_MARKER"

        # 2. tool_result 应该回流，含主进程 handler 的 "pong: ..." 响应
        ping_results = [
            e for e in bus.events
            if e[0] == "agent.tool_result"
            and e[1].get("tool_call_id") == ping_calls[0][1]["tool_call_id"]
        ]
        assert len(ping_results) == 1
        assert "E2E_MCP_MARKER" in str(ping_results[0][1]["result"])
        assert "pong" in str(ping_results[0][1]["result"]).lower()

        # 3. claude 最终输出含 DONE
        assert "DONE" in str(result.agent_run.result.output).upper()

    def test_executor_cleans_up_socket_and_config_after_run(self):
        """run() 结束后 mcp-config 文件 + socket 都应清理。"""
        ex = _make_executor(enable_mcp=True)
        _run(ex.run("Reply with exactly: PONG"))

        # proxy 应已 stop
        assert ex._proxy is None
        # mcp-config 文件应已删
        assert ex._mcp_config_file is None
        # serve_task 应已 cancel
        assert ex._mcp_serve_task is None

    def test_enable_mcp_false_skips_mcp_setup(self):
        """enable_mcp=False 时不启动 proxy，claude 没有 mcp__harness__* 工具。"""
        bus = FakeBus()
        ex = _make_executor(bus=bus, enable_mcp=False)
        _run(ex.run("Reply with exactly: PONG"))

        # 没有 mcp 相关 setup
        assert ex._proxy is None
        assert ex._mcp_config_file is None
