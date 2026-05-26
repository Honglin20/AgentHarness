"""Tests for AutoCompact middleware.

Demonstrates the required test layout for every extension:
  1. Unit tests — pure logic with a mock summarizer; no LLM calls.
  2. Integration test — registered on a real Bus, run through
     run_middleware_chain end-to-end.
  3. Disabled test — flipping `enabled=False` makes it a no-op even
     when registered.
"""

from __future__ import annotations

import pytest

from harness.extensions.base import NodeCtx, WorkflowCtx
from harness.extensions.bus import Bus
from harness.extensions.compact.auto_compact import AutoCompact


def _ctx(messages: list[dict]) -> NodeCtx:
    wf = WorkflowCtx(workflow_id="w", workflow_name="t", inputs={})
    return NodeCtx(
        workflow=wf,
        node_id="a",
        agent_name="a",
        prompt="(unused in compact tests)",
        messages=messages,
        upstream_outputs={},
    )


async def _fake_summarizer(text: str) -> str:
    return f"SUMMARY({len(text)}ch)"


# ---------- Unit ----------

@pytest.mark.asyncio
async def test_no_op_below_threshold():
    mw = AutoCompact(threshold_tokens=1000, keep_recent=2, summarizer=_fake_summarizer)
    ctx = _ctx([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
    out = await mw.before_node(ctx)
    assert out is ctx
    assert len(ctx.messages) == 2
    assert "auto_compact" not in ctx.metadata


@pytest.mark.asyncio
async def test_no_op_when_message_count_below_keep_recent():
    """Even with a flood of huge text, if msg count <= keep_recent, do nothing."""
    mw = AutoCompact(threshold_tokens=100, keep_recent=4, summarizer=_fake_summarizer)
    ctx = _ctx([{"role": "user", "content": "x" * 5000}])
    out = await mw.before_node(ctx)
    assert len(out.messages) == 1


@pytest.mark.asyncio
async def test_compacts_when_over_threshold():
    mw = AutoCompact(threshold_tokens=200, keep_recent=2, summarizer=_fake_summarizer)
    msgs = [
        {"role": "user",      "content": "x" * 400},   # ~100 tokens
        {"role": "assistant", "content": "y" * 400},   # ~100 tokens
        {"role": "user",      "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]
    ctx = _ctx(msgs)
    out = await mw.before_node(ctx)

    assert len(out.messages) == 3  # 1 summary + keep_recent (2)
    assert out.messages[0]["role"] == "system"
    assert out.messages[0]["content"].startswith("[Compacted earlier context]: SUMMARY")
    assert out.messages[-1]["content"] == "a1"
    assert out.messages[-2]["content"] == "q1"
    assert ctx.metadata["auto_compact"]["compacted"] is True
    assert ctx.metadata["auto_compact"]["dropped_messages"] == 2


@pytest.mark.asyncio
async def test_disabled_flag_skips_work():
    mw = AutoCompact(
        threshold_tokens=100, keep_recent=1,
        summarizer=_fake_summarizer, enabled=False,
    )
    msgs = [{"role": "user", "content": "x" * 5000}, {"role": "assistant", "content": "y"}]
    ctx = _ctx(msgs)
    out = await mw.before_node(ctx)
    assert len(out.messages) == 2
    assert "auto_compact" not in ctx.metadata


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        AutoCompact(keep_recent=0)
    with pytest.raises(ValueError):
        AutoCompact(threshold_tokens=50)


# ---------- Integration ----------

@pytest.mark.asyncio
async def test_integration_with_bus():
    """Registered on the Bus, it runs in the middleware chain end-to-end."""
    bus = Bus()
    bus.register(AutoCompact(
        threshold_tokens=200, keep_recent=1, summarizer=_fake_summarizer,
    ))

    ctx = _ctx([
        {"role": "user",      "content": "x" * 400},
        {"role": "assistant", "content": "y" * 400},
        {"role": "user",      "content": "last"},
    ])
    out = await bus.run_middleware_chain("before_node", ctx)

    assert isinstance(out, NodeCtx)
    assert len(out.messages) == 2
    assert out.messages[0]["role"] == "system"
    assert out.messages[1]["content"] == "last"


@pytest.mark.asyncio
async def test_runs_after_lower_priority_middleware():
    """before_node chain runs low-priority first, so compact (100) sees
    whatever a lower-priority middleware injected (e.g. memory at p=50).
    """
    from harness.extensions.base import BaseMiddleware

    class Injector(BaseMiddleware):
        name = "inject"
        priority = 50  # earlier than compact
        async def before_node(self, ctx):
            ctx.messages.insert(0, {"role": "system", "content": "z" * 1000})
            return ctx

    bus = Bus()
    bus.register(Injector())
    bus.register(AutoCompact(threshold_tokens=200, keep_recent=1, summarizer=_fake_summarizer))

    ctx = _ctx([{"role": "user", "content": "hi"}, {"role": "user", "content": "keep"}])
    out = await bus.run_middleware_chain("before_node", ctx)

    # Injector ran first → compact saw 3 messages and compacted them.
    assert len(out.messages) == 2
    assert out.messages[0]["role"] == "system"
    assert "Compacted" in out.messages[0]["content"]


# ---------- Off-state ----------

@pytest.mark.asyncio
async def test_unregistered_has_no_effect():
    """When AutoCompact is not registered, the bus chain is a pure pass-through."""
    bus = Bus()  # no registrations
    msgs = [{"role": "user", "content": "x" * 50000}]
    ctx = _ctx(msgs)
    out = await bus.run_middleware_chain("before_node", ctx)
    assert out.messages == msgs
