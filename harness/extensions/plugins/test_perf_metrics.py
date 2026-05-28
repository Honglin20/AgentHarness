"""Tests for PerfMetricsPlugin — combined token usage chart."""
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
async def test_emits_combined_bar_chart_with_hue():
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
    payload = event["payload"]
    assert payload["chart_type"] == "bar"
    assert payload["label"] == "Token Usage"
    assert payload["title"] == "Token Usage by Agent"
    assert payload["hue"] == "kind"
    # 2 rows: input + output
    assert len(payload["data"]) == 2
    agents = [d["agent"] for d in payload["data"]]
    assert all(a == "coder" for a in agents)
    kinds = [d["kind"] for d in payload["data"]]
    assert "input" in kinds
    assert "output" in kinds


@pytest.mark.asyncio
async def test_accumulates_across_agents():
    plugin = PerfMetricsPlugin()
    bus = Bus()
    bus.register(plugin)

    # First agent
    ctx1 = _make_node_ctx("analyzer", metadata={
        "analyzer": {"token_usage": {"input": 200, "output": 100, "total": 300}},
    })
    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx1, "result")

    event1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert len(event1["payload"]["data"]) == 2  # 1 agent × 2 kinds

    # Second agent
    ctx2 = _make_node_ctx("coder", metadata={
        "coder": {"token_usage": {"input": 50, "output": 80, "total": 130}},
    })
    await bus.run_hooks("on_node_end", ctx2, "result")

    event2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    data = event2["payload"]["data"]
    assert len(data) == 4  # 2 agents × 2 kinds
    agents = set(d["agent"] for d in data)
    assert agents == {"analyzer", "coder"}


@pytest.mark.asyncio
async def test_no_emit_when_no_token_usage():
    plugin = PerfMetricsPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_node_ctx()

    await bus.run_hooks("on_node_end", ctx, "result")
    assert ctx._side_effects == []
