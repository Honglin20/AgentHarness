"""Tests for PerfMetricsPlugin — now a no-op (charts moved to frontend Run Summary)."""
from __future__ import annotations

import pytest

from harness.extensions import NodeCtx, WorkflowCtx
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
async def test_plugin_is_noop():
    plugin = PerfMetricsPlugin()
    bus = Bus()
    bus.register(plugin)

    ctx = _make_node_ctx(metadata={
        "coder": {"duration_ms": 1500, "token_usage": {"input": 100, "output": 50, "total": 150}},
    })

    await bus.run_hooks("on_node_end", ctx, "result")

    # No side effects, no chart.render events
    assert ctx._side_effects == []
