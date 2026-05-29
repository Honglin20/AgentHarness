"""Tests for StepCounterPlugin."""
import asyncio
import pytest
from harness.extensions.plugins.step_counter import StepCounterPlugin
from harness.extensions.base import NodeCtx, WorkflowCtx


def _make_ctx(wid="w1", agent="agent1", meta=None):
    ctx = NodeCtx(
        workflow=WorkflowCtx(workflow_id=wid, workflow_name="test", inputs={}),
        node_id=agent,
        agent_name=agent,
        prompt="",
        messages=[],
        upstream_outputs={},
        config=None,
        metadata=meta or {agent: {"duration_ms": 100}},
    )
    return ctx


@pytest.mark.asyncio
async def test_step_counter_empty_node():
    plugin = StepCounterPlugin()
    ctx = _make_ctx()
    await plugin.on_node_end(ctx, "output")
    summary = plugin.get_summary("w1")
    assert summary["total_tool_calls"] == 0
    assert summary["total_llm_calls"] == 1  # at least 1 LLM call per node
    assert summary["nodes"]["agent1"]["tool_calls"] == 0


@pytest.mark.asyncio
async def test_step_counter_with_tool_calls():
    plugin = StepCounterPlugin()
    ctx = _make_ctx(meta={"agent1": {
        "duration_ms": 100,
        "tool_calls": [
            {"tool_name": "read_file"},
            {"tool_name": "write_file"},
        ],
    }})
    await plugin.on_node_end(ctx, "output")
    summary = plugin.get_summary("w1")
    assert summary["total_tool_calls"] == 2
    assert summary["nodes"]["agent1"]["tool_calls"] == 2


@pytest.mark.asyncio
async def test_step_counter_multiple_nodes():
    plugin = StepCounterPlugin()
    ctx1 = _make_ctx(agent="agent1", meta={"agent1": {"duration_ms": 50, "tool_calls": [{"tool_name": "search"}]}})
    await plugin.on_node_end(ctx1, "out1")
    ctx2 = _make_ctx(agent="agent2", meta={"agent2": {"duration_ms": 80, "tool_calls": [{"tool_name": "read"}, {"tool_name": "write"}]}})
    await plugin.on_node_end(ctx2, "out2")
    summary = plugin.get_summary("w1")
    assert summary["total_tool_calls"] == 3
    assert len(summary["nodes"]) == 2


@pytest.mark.asyncio
async def test_step_counter_emits_side_effect():
    plugin = StepCounterPlugin()
    ctx = _make_ctx(meta={"agent1": {"duration_ms": 100, "tool_calls": [{"tool_name": "search"}]}})
    await plugin.on_node_end(ctx, "output")
    assert len(ctx._side_effects) == 1
    assert ctx._side_effects[0]["type"] == "step.summary"
    payload = ctx._side_effects[0]["payload"]
    assert payload["node_tool_calls"] == 1
    assert payload["total_tool_calls"] == 1


def test_step_counter_unknown_workflow():
    plugin = StepCounterPlugin()
    summary = plugin.get_summary("nonexistent")
    assert summary["total_tool_calls"] == 0
