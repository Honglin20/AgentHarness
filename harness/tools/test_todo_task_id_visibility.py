"""Tests for Bug 1 fix: TodoTool must surface task_id format to the LLM.

Before the fix, the tool returned positional strings like "Step 1 ..." and
list output like "[1/9] ..." — the LLM had no way to discover the real
``t_N`` task_id format and would call ``task_id=1``, getting not-found
errors forever.

These tests pin the LLM-visible strings so the t_N IDs stay embedded.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic_ai import Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.todo import TodoItem, TodoToolFactory


def _make_tool():
    """Build the TodoTool closure exactly as the registry does."""
    factory = TodoToolFactory(event_bus=None)
    return factory.create()


async def _call(tool, deps=None, **kwargs):
    """Invoke the inner todo() coroutine directly.

    Coerce ``items`` dicts to ``TodoItem`` so the closure sees the same
    shape pydantic-ai would pass after arg validation. Reuse ``deps``
    across calls to preserve per-node TodoState.
    """
    inner = tool.function
    if deps is None:
        deps = AgentDeps(workflow_id="wf-1", node_id="scout", agent_name="scout")
    ctx = SimpleNamespace(deps=deps)
    if "items" in kwargs and kwargs["items"] is not None:
        kwargs["items"] = [
            it if isinstance(it, TodoItem) else TodoItem(**it)
            for it in kwargs["items"]
        ]
    return await inner(ctx, **kwargs)


def _fresh_deps():
    """Each test gets its own AgentDeps so state is isolated."""
    return AgentDeps(workflow_id="wf-1", node_id="scout", agent_name="scout")


# All tests run under asyncio.
pytestmark = pytest.mark.asyncio


async def test_create_returns_task_ids():
    """op='create' return string must embed the actual t_N task_ids, not
    positional 'Step 1'."""
    tool = _make_tool()
    deps = _fresh_deps()
    result = await _call(
        tool, deps,
        op="create",
        items=[
            {"content": "Analyze train.py", "activeForm": "Analyzing train.py..."},
            {"content": "Confirm targets", "activeForm": "Confirming targets..."},
        ],
    )
    # Both task_ids must be visible so the LLM can address them later.
    assert "t_1=" in result
    assert "t_2=" in result
    assert "Analyze train.py" in result
    # Active pointer must use the task_id, not positional language.
    assert "Active: t_1" in result


async def test_list_output_shows_task_id_per_row():
    """op='list' must prefix each row with the task_id."""
    tool = _make_tool()
    deps = _fresh_deps()
    await _call(
        tool, deps,
        op="create",
        items=[{"content": f"step {i}", "activeForm": f"step {i}"} for i in range(3)],
    )
    listed = await _call(tool, deps, op="list")
    lines = listed.splitlines()
    assert len(lines) == 3
    assert "t_1" in lines[0]
    assert "t_2" in lines[1]
    assert "t_3" in lines[2]


async def test_update_with_wrong_task_id_lists_valid_ids():
    """The error message must list valid IDs so the LLM self-corrects
    on the next turn (Rule 12 — fail loud)."""
    tool = _make_tool()
    deps = _fresh_deps()
    await _call(
        tool, deps,
        op="create",
        items=[{"content": "a", "activeForm": "a"} for _ in range(2)],
    )
    result = await _call(tool, deps, op="update", task_id="1", status="completed")
    assert "task_id '1' not found" in result
    assert "Valid IDs: t_1, t_2" in result
    assert "op='list'" in result


async def test_update_with_missing_task_id_lists_valid_ids():
    tool = _make_tool()
    deps = _fresh_deps()
    await _call(
        tool, deps,
        op="create",
        items=[{"content": "a", "activeForm": "a"}],
    )
    result = await _call(tool, deps, op="update", status="completed")
    assert "task_id is required" in result
    assert "Valid IDs: t_1" in result


async def test_replace_returns_new_task_ids():
    """op='replace' must surface the new IDs."""
    tool = _make_tool()
    deps = _fresh_deps()
    await _call(tool, deps, op="create", items=[{"content": "old", "activeForm": "old"}])
    result = await _call(
        tool, deps,
        op="replace",
        items=[
            {"content": "new-a", "activeForm": "new-a"},
            {"content": "new-b", "activeForm": "new-b"},
        ],
    )
    assert "t_2=" in result  # counter continued after the original t_1
    assert "t_3=" in result
    assert "Active: t_2" in result


async def test_complete_remaining_lists_closed_ids():
    """op='complete_remaining' return must list the closed IDs."""
    tool = _make_tool()
    deps = _fresh_deps()
    await _call(
        tool, deps,
        op="create",
        items=[{"content": f"s{i}", "activeForm": f"s{i}"} for i in range(3)],
    )
    result = await _call(tool, deps, op="complete_remaining", status="completed", reason="done early")
    assert "Closed IDs: t_1, t_2, t_3" in result
