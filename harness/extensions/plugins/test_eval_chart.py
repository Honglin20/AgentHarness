"""Tests for EvalChartPlugin — extracts judge scores and emits line chart."""
from __future__ import annotations

import asyncio
import pytest

from harness.extensions import BaseHook, NodeCtx, WorkflowCtx
from harness.extensions.bus import Bus


def _make_judge_ctx(judge_name: str = "_judge_coder", target_name: str = "coder") -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    return NodeCtx(
        workflow=wf,
        node_id=judge_name,
        agent_name=judge_name,
        prompt="",
        messages=[],
        upstream_outputs={},
    )


class FakeReviewOutput:
    def __init__(self, score: float | None, decision: str = "pass"):
        self.score = score
        self.decision = decision
        self.reason = "ok"


@pytest.mark.asyncio
async def test_emits_chart_when_judge_has_score():
    from harness.extensions.plugins.eval_chart import EvalChartPlugin

    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_judge_ctx()
    ctx.metadata["_judge_coder"] = {"score_history": [0.6, 0.7]}

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, FakeReviewOutput(score=0.85))

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "chart.render"
    assert event["payload"]["chart_type"] == "line"
    assert event["payload"]["x"] == "iteration"
    assert event["payload"]["y"] == "score"
    assert event["payload"]["label"] == "Eval Scores"
    assert event["payload"]["title"] == "coder quality"
    assert len(event["payload"]["data"]) == 3  # 0.6, 0.7, 0.85


@pytest.mark.asyncio
async def test_no_emit_when_not_judge_node():
    from harness.extensions.plugins.eval_chart import EvalChartPlugin

    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_judge_ctx(judge_name="coder", target_name="coder")

    await bus.run_hooks("on_node_end", ctx, FakeReviewOutput(score=0.9))
    # No side effects means no events emitted
    assert ctx._side_effects == []


@pytest.mark.asyncio
async def test_no_emit_when_score_is_none():
    from harness.extensions.plugins.eval_chart import EvalChartPlugin

    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_judge_ctx()

    await bus.run_hooks("on_node_end", ctx, FakeReviewOutput(score=None))
    assert ctx._side_effects == []


@pytest.mark.asyncio
async def test_score_history_accumulates():
    from harness.extensions.plugins.eval_chart import EvalChartPlugin

    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)
    ctx = _make_judge_ctx()
    await bus.run_hooks("on_node_end", ctx, FakeReviewOutput(score=0.5))
    history = ctx.metadata.get("_judge_coder", {}).get("score_history", [])
    assert 0.5 in history