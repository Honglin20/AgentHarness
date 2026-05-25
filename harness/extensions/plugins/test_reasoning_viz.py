"""Tests for ReasoningVizPlugin — extracts reasoning steps from messages."""
from __future__ import annotations

import asyncio
import pytest

from harness.extensions import BaseHook, NodeCtx, WorkflowCtx
from harness.extensions.bus import Bus


def _make_node_ctx(messages=None) -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    return NodeCtx(
        workflow=wf, node_id="analyst", agent_name="analyst",
        prompt="", messages=messages or [], upstream_outputs={},
    )


@pytest.mark.asyncio
async def test_emits_reasoning_when_chain_of_thought_present():
    from harness.extensions.plugins.reasoning_viz import ReasoningVizPlugin

    plugin = ReasoningVizPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx(messages=[
        {"role": "assistant", "content": "Let me think step by step. First, I need to analyze the data. Then, I will draw conclusions."},
    ])

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, "result")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "reasoning.render"
    assert event["payload"]["agent_name"] == "analyst"
    assert len(event["payload"]["steps"]) > 0


@pytest.mark.asyncio
async def test_no_emit_when_no_reasoning_detected():
    from harness.extensions.plugins.reasoning_viz import ReasoningVizPlugin

    plugin = ReasoningVizPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx(messages=[
        {"role": "assistant", "content": "Here is the answer: 42"},
    ])

    await bus.run_hooks("on_node_end", ctx, "42")
    assert ctx._side_effects == []