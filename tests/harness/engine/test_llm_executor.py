"""Tests for LLMExecutor tool_calls collection."""
from unittest.mock import MagicMock

from harness.engine.llm_executor import LLMExecutor


def test_tool_calls_collected():
    """LLMExecutor collects tool call name, args, and result."""
    executor = LLMExecutor(
        MagicMock(), MagicMock(),
        event_bus=None, workflow_id="wf1", node_id="a1", agent_name="a1",
    )

    call_part = MagicMock()
    call_part.tool_name = "bash"
    call_part.args = {"command": "ls -la"}
    call_part.tool_call_id = "call_01"

    result_part = MagicMock()
    result_part.tool_name = "bash"
    result_part.content = "file1.txt\nfile2.txt"
    result_part.tool_call_id = "call_01"

    executor._emit_tool_call(call_part)
    executor._emit_tool_result(result_part)

    assert len(executor.tool_calls) == 1
    assert executor.tool_calls[0]["tool_name"] == "bash"
    assert executor.tool_calls[0]["tool_args"] == {"command": "ls -la"}
    assert executor.tool_calls[0]["tool_result"] == "file1.txt\nfile2.txt"


def test_tool_calls_multiple():
    """Multiple tool calls are collected in order."""
    executor = LLMExecutor(
        MagicMock(), MagicMock(),
        event_bus=None, workflow_id="wf1", node_id="a1", agent_name="a1",
    )

    for i, name in enumerate(["bash", "bash", "write_file"]):
        cp = MagicMock()
        cp.tool_name = name
        cp.args = {"cmd": name}
        cp.tool_call_id = f"call_{i}"
        executor._emit_tool_call(cp)

        rp = MagicMock()
        rp.tool_name = name
        rp.content = f"result_{name}"
        rp.tool_call_id = f"call_{i}"
        executor._emit_tool_result(rp)

    assert len(executor.tool_calls) == 3
    assert executor.tool_calls[0]["tool_name"] == "bash"
    assert executor.tool_calls[2]["tool_name"] == "write_file"


def test_tool_calls_empty_when_no_tools():
    """Empty tool_calls when no tools are called."""
    executor = LLMExecutor(
        MagicMock(), MagicMock(),
        event_bus=None, workflow_id="wf1", node_id="a1", agent_name="a1",
    )
    assert executor.tool_calls == []
