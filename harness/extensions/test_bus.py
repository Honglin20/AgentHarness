"""P0 sanity tests for the extension Bus.

These tests prove:
  - Empty registry behaves like a no-op (backwards compat).
  - Hooks fire concurrently and exceptions don't crash the bus.
  - Middleware chain runs in priority order and short-circuits on Reject.
  - Legacy EventBus / get_event_bus aliases still work.
"""

from __future__ import annotations

import asyncio
import pytest

from harness.extensions import (
    BaseHook,
    BaseMiddleware,
    BaseGraphMutator,
    NodeCtx,
    RejectAction,
    RetryAction,
    ToolCtx,
    WorkflowCtx,
)
from harness.extensions.bus import Bus


def _make_node_ctx(**overrides) -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={})
    defaults = dict(
        workflow=wf,
        node_id="agent_a",
        agent_name="agent_a",
        prompt="hello",
        messages=[],
        upstream_outputs={},
    )
    defaults.update(overrides)
    return NodeCtx(**defaults)


# ---------- Hooks ----------

@pytest.mark.asyncio
async def test_hook_concurrent_fire_and_exception_isolation():
    bus = Bus()

    fired: list[str] = []

    class GoodHook(BaseHook):
        name = "good"
        async def on_node_start(self, ctx: NodeCtx) -> None:
            fired.append("good")

    class BadHook(BaseHook):
        name = "bad"
        async def on_node_start(self, ctx: NodeCtx) -> None:
            raise RuntimeError("boom")

    class AnotherGoodHook(BaseHook):
        name = "another"
        async def on_node_start(self, ctx: NodeCtx) -> None:
            fired.append("another")

    bus.register(GoodHook())
    bus.register(BadHook())
    bus.register(AnotherGoodHook())

    await bus.run_hooks("on_node_start", _make_node_ctx())

    # Both good hooks fired; bad hook did not stop them
    assert set(fired) == {"good", "another"}


@pytest.mark.asyncio
async def test_empty_bus_is_no_op():
    bus = Bus()
    # Should not raise even with zero extensions
    await bus.run_hooks("on_node_start", _make_node_ctx())
    result = await bus.run_middleware_chain("before_node", _make_node_ctx())
    assert isinstance(result, NodeCtx)


# ---------- Middleware ----------

@pytest.mark.asyncio
async def test_middleware_runs_in_priority_order_before():
    bus = Bus()
    order: list[str] = []

    class MwA(BaseMiddleware):
        name = "a"
        priority = 10
        async def before_node(self, ctx: NodeCtx):
            order.append("a")
            return ctx

    class MwB(BaseMiddleware):
        name = "b"
        priority = 5
        async def before_node(self, ctx: NodeCtx):
            order.append("b")
            return ctx

    bus.register(MwA())
    bus.register(MwB())
    await bus.run_middleware_chain("before_node", _make_node_ctx())
    assert order == ["b", "a"]  # priority 5 before 10


@pytest.mark.asyncio
async def test_middleware_after_runs_high_first():
    bus = Bus()
    order: list[str] = []

    class MwA(BaseMiddleware):
        name = "a"
        priority = 10
        async def after_node(self, ctx, output):
            order.append("a")
            return output

    class MwB(BaseMiddleware):
        name = "b"
        priority = 5
        async def after_node(self, ctx, output):
            order.append("b")
            return output

    bus.register(MwA())
    bus.register(MwB())
    ctx = _make_node_ctx()
    await bus.run_middleware_chain("after_node", (ctx, "out"))
    assert order == ["a", "b"]  # high priority first in after_*


@pytest.mark.asyncio
async def test_middleware_can_reject():
    bus = Bus()

    class Blocker(BaseMiddleware):
        name = "block"
        async def before_node(self, ctx):
            return RejectAction(reason="nope")

    class Later(BaseMiddleware):
        name = "later"
        priority = 100
        async def before_node(self, ctx):
            raise AssertionError("should not run after reject")

    bus.register(Blocker())
    bus.register(Later())
    result = await bus.run_middleware_chain("before_node", _make_node_ctx())
    assert isinstance(result, RejectAction)
    assert result.reason == "nope"


@pytest.mark.asyncio
async def test_middleware_can_request_retry():
    bus = Bus()

    class JudgeMw(BaseMiddleware):
        name = "judge"
        async def after_node(self, ctx, output):
            return RetryAction(new_prompt="try again", max_attempts=2)

    bus.register(JudgeMw())
    result = await bus.run_middleware_chain("after_node", (_make_node_ctx(), "bad"))
    assert isinstance(result, RetryAction)
    assert result.new_prompt == "try again"


@pytest.mark.asyncio
async def test_middleware_exception_skips_only_that_one():
    bus = Bus()

    class Broken(BaseMiddleware):
        name = "broken"
        priority = 5
        async def before_node(self, ctx):
            raise ValueError("oops")

    class Good(BaseMiddleware):
        name = "good"
        priority = 10
        async def before_node(self, ctx):
            ctx.prompt = "modified"
            return ctx

    bus.register(Broken())
    bus.register(Good())
    result = await bus.run_middleware_chain("before_node", _make_node_ctx())
    assert isinstance(result, NodeCtx)
    assert result.prompt == "modified"


# ---------- GraphMutator ----------

def test_graph_mutator_registered_separately():
    bus = Bus()

    class M(BaseGraphMutator):
        name = "m"
        def mutate(self, workflow):
            return workflow

    bus.register(M())
    assert len(bus.get_mutators()) == 1


def test_register_rejects_unrecognized_object():
    bus = Bus()
    class Random:
        name = "x"
    with pytest.raises(TypeError):
        bus.register(Random())


# ---------- Backwards compat ----------

def test_legacy_event_bus_imports_still_work():
    from server.event_bus import EventBus, get_event_bus
    eb = get_event_bus()
    assert isinstance(eb, EventBus)
    # Old emit() API works
    eb.emit("test.event", {"x": 1})


def test_emit_does_not_invoke_hooks():
    """emit() is the WS path; hooks only fire via run_hooks(). Two separate channels."""
    bus = Bus()
    called: list[str] = []

    class H(BaseHook):
        name = "h"
        async def on_node_start(self, ctx):
            called.append("hit")

    bus.register(H())
    bus.emit("node.start", {"node_id": "x"})
    assert called == []


# ---------- NodeCtx emit ----------

def test_node_ctx_emit_appends_side_effects():
    ctx = _make_node_ctx()
    assert ctx._side_effects == []
    ctx.emit("chart.render", {"chart_type": "line"})
    assert len(ctx._side_effects) == 1
    assert ctx._side_effects[0]["type"] == "chart.render"
    assert ctx._side_effects[0]["payload"]["chart_type"] == "line"


def test_node_ctx_emit_multiple():
    ctx = _make_node_ctx()
    ctx.emit("chart.render", {"a": 1})
    ctx.emit("metric.report", {"b": 2})
    assert len(ctx._side_effects) == 2
    assert ctx._side_effects[0]["type"] == "chart.render"
    assert ctx._side_effects[1]["type"] == "metric.report"


# ---------- Bus flush side effects ----------

@pytest.mark.asyncio
async def test_run_hooks_flushes_side_effects():
    bus = Bus()

    class ChartHook(BaseHook):
        name = "chart"
        async def on_node_end(self, ctx: NodeCtx, output) -> None:
            ctx.emit("chart.render", {"chart_type": "line", "data": []})

    bus.register(ChartHook())
    ctx = _make_node_ctx()
    sub_id, queue = await bus.subscribe()

    await bus.run_hooks("on_node_end", ctx, "output")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "chart.render"
    assert event["payload"]["chart_type"] == "line"
    assert ctx._side_effects == []


@pytest.mark.asyncio
async def test_run_hooks_no_side_effects_is_no_op():
    bus = Bus()
    ctx = _make_node_ctx()
    await bus.run_hooks("on_node_end", ctx, "output")
    assert ctx._side_effects == []


@pytest.mark.asyncio
async def test_run_hooks_multiple_side_effects_flush_in_order():
    bus = Bus()

    class MultiHook(BaseHook):
        name = "multi"
        async def on_node_end(self, ctx: NodeCtx, output) -> None:
            ctx.emit("chart.render", {"order": 1})
            ctx.emit("metric.report", {"order": 2})

    bus.register(MultiHook())
    ctx = _make_node_ctx()
    sub_id, queue = await bus.subscribe()

    await bus.run_hooks("on_node_end", ctx, "output")

    e1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    e2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert e1["type"] == "chart.render"
    assert e2["type"] == "metric.report"
    assert ctx._side_effects == []
