"""Tests for PerfMetricsPlugin — token usage and latency metrics."""
from __future__ import annotations

import asyncio
import pytest

from harness.extensions import BaseHook, NodeCtx, WorkflowCtx
from harness.extensions.bus import Bus
from harness.extensions.plugins.perf_metrics import PerfMetricsPlugin


def _make_node_ctx(agent_name: str = "coder", metadata: dict | None = None) -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    ctx = NodeCtx(
        workflow=wf, node_id=agent_name, agent_name=agent_name,
        prompt="", messages=[], upstream_outputs={},
    )
    if metadata:
        ctx.metadata.update(metadata)
    return ctx


@pytest.mark.asyncio
async def test_emits_bar_chart_for_token_usage():
    plugin = PerfMetricsPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx(metadata={
        "coder": {"duration_ms": 1500, "token_usage": {"input": 100, "output": 50, "total": 150}},
    })

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, "result")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "chart.render"
    assert event["payload"]["chart_type"] == "bar"
    assert event["payload"]["label"] == "Token Usage"


@pytest.mark.asyncio
async def test_no_emit_when_no_token_usage():
    plugin = PerfMetricsPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx()

    await bus.run_hooks("on_node_end", ctx, "result")
    assert ctx._side_effects == []