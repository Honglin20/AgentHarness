"""Unit tests for LLMExecutor tool_call/tool_result ID-based matching.

Covers the parallel-same-name-tool-call bug: pydantic-ai yields ALL
function_tool_call events upfront, then function_tool_result events as
each completes. The result must pair to its originating call by
``tool_call_id`` — never by reversed name-based matching.
"""

from __future__ import annotations

from types import SimpleNamespace

from harness.engine.llm_executor import LLMExecutor


def _make_executor() -> LLMExecutor:
    """Bare executor — no agent, no bus. Only self.tool_calls matters."""
    return LLMExecutor(pydantic_agent=None, deps=None)


def _call_part(tool_name: str, tool_call_id: str, args: dict | None = None):
    return SimpleNamespace(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        args=args or {},
    )


def _result_part(tool_name: str, tool_call_id: str, content: str):
    return SimpleNamespace(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        content=content,
    )


def test_emit_tool_call_stores_tool_call_id():
    """Entry in self.tool_calls must carry tool_call_id."""
    ex = _make_executor()
    ex._emit_tool_call(_call_part("bash", "call_1", {"cmd": "ls"}))
    assert ex.tool_calls[0]["tool_call_id"] == "call_1"
    assert ex.tool_calls[0]["tool_name"] == "bash"
    assert ex.tool_calls[0]["tool_args"] == {"cmd": "ls"}


def test_parallel_same_name_tool_calls_match_by_id():
    """Reproduces the original bug: two parallel bash calls must NOT have
    their results crossed. Result for call A lands on entry A only."""
    ex = _make_executor()
    # pydantic-ai yields both calls upfront.
    ex._emit_tool_call(_call_part("bash", "A", {"cmd": "ls"}))
    ex._emit_tool_call(_call_part("bash", "B", {"cmd": "pwd"}))
    # Result for A arrives first.
    ex._emit_tool_result(_result_part("bash", "A", "result-for-A"))

    assert ex.tool_calls[0]["tool_call_id"] == "A"
    assert ex.tool_calls[0].get("tool_result") == "result-for-A"
    # The bug would have written "result-for-A" onto entry B (the last
    # pending same-name entry). B must still be result-less.
    assert ex.tool_calls[1]["tool_call_id"] == "B"
    assert "tool_result" not in ex.tool_calls[1]

    # Now result for B arrives — lands on B only.
    ex._emit_tool_result(_result_part("bash", "B", "result-for-B"))
    assert ex.tool_calls[0]["tool_result"] == "result-for-A"
    assert ex.tool_calls[1]["tool_result"] == "result-for-B"


def test_emit_tool_result_unknown_tool_call_id_drops(caplog):
    """Unknown tool_call_id must not pollute any existing entry."""
    import logging
    ex = _make_executor()
    ex._emit_tool_call(_call_part("bash", "A"))
    with caplog.at_level(logging.WARNING):
        ex._emit_tool_result(_result_part("bash", "Z", "orphan"))
    assert "tool_result" not in ex.tool_calls[0]
    assert any("tool_call_id=Z" in rec.getMessage() for rec in caplog.records)


def test_emit_tool_result_without_tool_call_id_drops():
    """Missing tool_call_id on the part must not fall back to name-based
    matching — that would re-introduce the original bug."""
    ex = _make_executor()
    ex._emit_tool_call(_call_part("bash", "A"))
    # Part lacks tool_call_id entirely.
    part = SimpleNamespace(tool_name="bash", content="no-id")
    ex._emit_tool_result(part)
    assert "tool_result" not in ex.tool_calls[0]
