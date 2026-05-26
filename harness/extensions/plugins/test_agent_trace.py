"""Tests for AgentTracePlugin — emits trace.step events for every node."""
from __future__ import annotations

import asyncio
import pytest

from harness.extensions import BaseHook, NodeCtx, WorkflowCtx
from harness.extensions.bus import Bus
from harness.extensions.plugins.agent_trace import AgentTracePlugin


def _make_node_ctx(agent_name: str = "coder") -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    return NodeCtx(
        workflow=wf, node_id=agent_name, agent_name=agent_name,
        prompt="do stuff", messages=[], upstream_outputs={},
    )


@pytest.mark.asyncio
async def test_emits_trace_step_on_node_end():
    plugin = AgentTracePlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx("coder")

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, "result text")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "trace.step"
    assert event["payload"]["agent_name"] == "coder"
    assert event["payload"]["status"] == "completed"


@pytest.mark.asyncio
async def test_trace_includes_workflow_id():
    plugin = AgentTracePlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx()

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, "out")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["payload"]["workflow_id"] == "w1"