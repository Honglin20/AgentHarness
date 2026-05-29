"""Tests for CircularDetectorPlugin."""
import pytest
from harness.extensions.plugins.circular_detector import CircularDetectorPlugin
from harness.extensions.base import NodeCtx, WorkflowCtx


def _make_ctx(wid="w1", agent="agent1", tool_calls=None):
    meta = {agent: {"duration_ms": 100}}
    if tool_calls is not None:
        meta[agent]["tool_calls"] = tool_calls
    return NodeCtx(
        workflow=WorkflowCtx(workflow_id=wid, workflow_name="test", inputs={}),
        node_id=agent,
        agent_name=agent,
        prompt="",
        messages=[],
        upstream_outputs={},
        config=None,
        metadata=meta,
    )


def test_not_circular_with_few_calls():
    plugin = CircularDetectorPlugin(threshold=3)
    calls = [
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "search", "tool_args": {"q": "test"}},
    ]
    assert not plugin._is_circular(calls)


def test_detects_repeated_tool_calls():
    plugin = CircularDetectorPlugin(threshold=3)
    calls = [
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "search", "tool_args": {"q": "test"}},
    ]
    assert plugin._is_circular(calls)


def test_not_circular_different_args():
    plugin = CircularDetectorPlugin(threshold=3)
    calls = [
        {"tool_name": "search", "tool_args": {"q": "test1"}},
        {"tool_name": "search", "tool_args": {"q": "test2"}},
        {"tool_name": "search", "tool_args": {"q": "test3"}},
    ]
    assert not plugin._is_circular(calls)


def test_not_circular_different_tools():
    plugin = CircularDetectorPlugin(threshold=3)
    calls = [
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "read", "tool_args": {"path": "a.txt"}},
        {"tool_name": "write", "tool_args": {"path": "b.txt"}},
    ]
    assert not plugin._is_circular(calls)


def test_circular_only_tail_matters():
    """Only the last N calls need to be identical."""
    plugin = CircularDetectorPlugin(threshold=3)
    calls = [
        {"tool_name": "search", "tool_args": {"q": "first"}},
        {"tool_name": "search", "tool_args": {"q": "repeat"}},
        {"tool_name": "search", "tool_args": {"q": "repeat"}},
        {"tool_name": "search", "tool_args": {"q": "repeat"}},
    ]
    assert plugin._is_circular(calls)


@pytest.mark.asyncio
async def test_emits_warning_on_circular():
    plugin = CircularDetectorPlugin(threshold=3)
    calls = [
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "search", "tool_args": {"q": "test"}},
        {"tool_name": "search", "tool_args": {"q": "test"}},
    ]
    ctx = _make_ctx(tool_calls=calls)
    await plugin.on_node_end(ctx, "output")
    assert len(ctx._side_effects) == 1
    assert ctx._side_effects[0]["type"] == "circular.warning"
    assert ctx._side_effects[0]["payload"]["last_tool"] == "search"


@pytest.mark.asyncio
async def test_no_warning_when_not_circular():
    plugin = CircularDetectorPlugin(threshold=3)
    ctx = _make_ctx(tool_calls=[
        {"tool_name": "search", "tool_args": {"q": "a"}},
        {"tool_name": "read", "tool_args": {"path": "b"}},
    ])
    await plugin.on_node_end(ctx, "output")
    assert len(ctx._side_effects) == 0


@pytest.mark.asyncio
async def test_no_warning_with_empty_calls():
    plugin = CircularDetectorPlugin(threshold=3)
    ctx = _make_ctx(tool_calls=[])
    await plugin.on_node_end(ctx, "output")
    assert len(ctx._side_effects) == 0
