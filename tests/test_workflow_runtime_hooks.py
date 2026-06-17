"""Tests for the workflow-level hook dispatch in arun_workflow.

Locks the fix for the pre-existing framework gap where on_workflow_start
/ on_workflow_end were defined on BaseHook but NEVER dispatched by the
engine (broke ConsoleOutput's workflow header, forced TuiRenderer to
use an explicit start() workaround).

These tests verify:
  1. arun_workflow dispatches on_workflow_start BEFORE ainvoke.
  2. arun_workflow dispatches on_workflow_end AFTER ainvoke on success.
  3. arun_workflow dispatches on_workflow_end EVEN WHEN ainvoke raises,
     so hooks can release resources (Live.stop, subscriber cancel) on
     the exception path.
  4. WorkflowCtx passed to hooks carries the correct workflow_id /
     workflow_name / inputs.
  5. Hooks without a bus (plain Workflow with no extensions) still work
     — the dispatch is a no-op, not a crash.

If any of these regress, ConsoleOutput's workflow header stops showing
and TuiRenderer's Live never starts — the original framework gap.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from harness.extensions.base import BaseHook, WorkflowCtx


class _RecordingHook(BaseHook):
    """Records every lifecycle call + the ctx it received."""

    name = "recording"

    def __init__(self):
        self.start_calls: list[WorkflowCtx] = []
        self.end_calls: list[tuple[WorkflowCtx, dict]] = []

    async def on_workflow_start(self, ctx: WorkflowCtx) -> None:
        self.start_calls.append(ctx)

    async def on_workflow_end(self, ctx: WorkflowCtx, result: dict) -> None:
        self.end_calls.append((ctx, result))


def _make_workflow_with_bus(thread_id: str = "wf-id"):
    """Build a minimal Workflow mock that arun_workflow can drive.

    arun_workflow touches:
      - workflow.mcp_servers (must be empty / setup-done)
      - workflow._mcp_setup_done (True to skip setup check)
      - workflow._compiled (mock with .ainvoke)
      - workflow._event_bus (real Bus with run_hooks)
      - workflow.name (for WorkflowCtx)
    """
    from harness.extensions.bus import Bus

    workflow = MagicMock()
    workflow.name = "test_wf"
    workflow.mcp_servers = []
    workflow._mcp_setup_done = True
    workflow._compiled = MagicMock()
    workflow._compiled.ainvoke = AsyncMock(return_value={
        "inputs": {"task": "x"},
        "outputs": {"alpha": {"summary": "done"}},
        "errors": {},
        "metadata": {},
    })
    workflow._event_bus = Bus()
    # Configure workflow.checkpointer to None so arun_workflow doesn't
    # try to read/write checkpoints.
    workflow.checkpointer = None
    # build_workflow_result reads workflow.agents — provide minimal list.
    from harness.core.agent import Agent
    workflow.agents = [Agent(name="alpha", after=[])]
    return workflow


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arun_workflow_dispatches_on_workflow_start():
    """on_workflow_start must fire before ainvoke."""
    workflow = _make_workflow_with_bus()
    hook = _RecordingHook()
    workflow._event_bus.register(hook)

    from harness.core.workflow_runtime import arun_workflow

    await arun_workflow(workflow, inputs={"task": "x"})

    assert len(hook.start_calls) == 1
    ctx = hook.start_calls[0]
    assert ctx.workflow_name == "test_wf"
    assert ctx.inputs == {"task": "x"}


@pytest.mark.asyncio
async def test_arun_workflow_dispatches_on_workflow_end_on_success():
    """on_workflow_end must fire after ainvoke returns."""
    workflow = _make_workflow_with_bus()
    hook = _RecordingHook()
    workflow._event_bus.register(hook)

    from harness.core.workflow_runtime import arun_workflow

    result = await arun_workflow(workflow, inputs={"task": "x"})

    assert len(hook.end_calls) == 1
    ctx, end_result = hook.end_calls[0]
    assert end_result["outputs"] == result.outputs
    assert end_result["errors"] == result.errors


@pytest.mark.asyncio
async def test_on_workflow_start_fires_before_on_workflow_end():
    """Order matters: TuiRenderer.on_workflow_start starts Live, then
    on_workflow_end stops it. Reversed order would crash."""
    workflow = _make_workflow_with_bus()
    order: list[str] = []

    class _OrderedHook(BaseHook):
        name = "ordered"

        async def on_workflow_start(self, ctx):
            order.append("start")

        async def on_workflow_end(self, ctx, result):
            order.append("end")

    workflow._event_bus.register(_OrderedHook())

    from harness.core.workflow_runtime import arun_workflow

    await arun_workflow(workflow, inputs={})
    assert order == ["start", "end"]


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_workflow_end_fires_on_ainvoke_failure():
    """When ainvoke raises, on_workflow_end must STILL fire so hooks
    can release Live / cancel subscribers / restore cursor. Without
    this, TuiRenderer would leave the terminal in a hide-cursor state
    on workflow failure."""
    workflow = _make_workflow_with_bus()
    workflow._compiled.ainvoke = AsyncMock(side_effect=RuntimeError("LLM exploded"))
    hook = _RecordingHook()
    workflow._event_bus.register(hook)

    from harness.core.workflow_runtime import arun_workflow

    with pytest.raises(RuntimeError, match="LLM exploded"):
        await arun_workflow(workflow, inputs={})

    # on_workflow_start fired (before the raise)
    assert len(hook.start_calls) == 1
    # on_workflow_end ALSO fired on the exception path
    assert len(hook.end_calls) == 1
    ctx, end_result = hook.end_calls[0]
    assert "_workflow" in end_result["errors"]


@pytest.mark.asyncio
async def test_hook_exception_during_end_does_not_mask_original():
    """If a hook raises inside on_workflow_end during the exception path,
    the original error must still propagate (don't let cleanup mask it)."""
    workflow = _make_workflow_with_bus()
    workflow._compiled.ainvoke = AsyncMock(side_effect=RuntimeError("original"))

    class _BrokenHook(BaseHook):
        name = "broken"

        async def on_workflow_end(self, ctx, result):
            raise ValueError("cleanup hook crashed")

    workflow._event_bus.register(_BrokenHook())

    from harness.core.workflow_runtime import arun_workflow

    # The original RuntimeError must surface, not the cleanup ValueError.
    with pytest.raises(RuntimeError, match="original"):
        await arun_workflow(workflow, inputs={})


# ---------------------------------------------------------------------------
# WorkflowCtx shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_ctx_carries_thread_id_from_config():
    """thread_id on WorkflowCtx must match config['configurable']['thread_id']
    so hooks can correlate with checkpointer state."""
    workflow = _make_workflow_with_bus()
    hook = _RecordingHook()
    workflow._event_bus.register(hook)

    from harness.core.workflow_runtime import arun_workflow

    config = {"configurable": {"thread_id": "cli-run-abc-123"}}
    await arun_workflow(workflow, inputs={"task": "x"}, config=config)

    assert hook.start_calls[0].workflow_id == "cli-run-abc-123"


@pytest.mark.asyncio
async def test_workflow_ctx_falls_back_to_workflow_name_when_no_config():
    workflow = _make_workflow_with_bus()
    hook = _RecordingHook()
    workflow._event_bus.register(hook)

    from harness.core.workflow_runtime import arun_workflow

    await arun_workflow(workflow, inputs={})  # no config

    # Falls back to workflow.name (no config = no thread_id)
    assert hook.start_calls[0].workflow_id == "test_wf"


# ---------------------------------------------------------------------------
# No-bus path (defensive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_bus_does_not_crash():
    """A Workflow constructed without a bus (plain script) must still
    run — hook dispatch is skipped, not crash."""
    workflow = _make_workflow_with_bus()
    workflow._event_bus = None  # simulate no bus

    from harness.core.workflow_runtime import arun_workflow

    # Should complete without raising
    result = await arun_workflow(workflow, inputs={"task": "x"})
    assert result is not None


@pytest.mark.asyncio
async def test_bus_without_run_hooks_does_not_crash():
    """Defensive: if a future Bus subclass doesn't implement run_hooks,
    arun_workflow should skip dispatch rather than AttributeError."""
    workflow = _make_workflow_with_bus()
    # Replace bus with a stub that lacks run_hooks
    workflow._event_bus = MagicMock(spec=[])  # empty interface

    from harness.core.workflow_runtime import arun_workflow

    result = await arun_workflow(workflow, inputs={"task": "x"})
    assert result is not None


# ---------------------------------------------------------------------------
# Interrupt path (langgraph.types.interrupt)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_workflow_end_NOT_dispatched_on_interrupt():
    """When langgraph.types.interrupt fires, ainvoke returns
    {__interrupt__: [...]} without raising. Dispatching on_workflow_end
    in this state would prematurely tear down Live (TuiRenderer) while
    the user is still looking at the prompt — and resume would flicker
    Live back up. Skip end dispatch on interrupt; resume re-fires start.

    Regression-lock for the bug reviewer found: interrupt is a PAUSE,
    not an END.
    """
    workflow = _make_workflow_with_bus()
    # Simulate langgraph interrupt: ainvoke returns __interrupt__ dict
    fake_interrupt = MagicMock()
    fake_interrupt.value = {"question": "pick one"}
    workflow._compiled.ainvoke = AsyncMock(return_value={
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
        "__interrupt__": [fake_interrupt],
    })
    hook = _RecordingHook()
    workflow._event_bus.register(hook)

    from harness.core.workflow_runtime import arun_workflow

    result = await arun_workflow(workflow, inputs={"task": "x"})

    # on_workflow_start DID fire (interrupt happens mid-workflow)
    assert len(hook.start_calls) == 1
    # on_workflow_end did NOT fire — workflow is paused, not ended
    assert len(hook.end_calls) == 0
    # Result correctly flagged as interrupted
    assert result.interrupted is True
    assert result.interrupt_value == {"question": "pick one"}


# ---------------------------------------------------------------------------
# Hook exception robustness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_raising_in_on_workflow_start_does_not_break_workflow():
    """A broken on_workflow_start hook is swallowed by Bus._safe_invoke
    (which emits ext.error); the workflow must proceed and on_workflow_end
    must still fire on completion.

    Without this guarantee, a TuiRenderer.on_workflow_start failure
    (Live.start raises) would leave resources in an inconsistent state
    with no cleanup path.
    """
    workflow = _make_workflow_with_bus()

    class _BrokenStartHook(BaseHook):
        name = "broken-start"

        async def on_workflow_start(self, ctx):
            raise RuntimeError("start hook crashed")

    end_hook = _RecordingHook()
    workflow._event_bus.register(_BrokenStartHook())
    workflow._event_bus.register(end_hook)

    from harness.core.workflow_runtime import arun_workflow

    result = await arun_workflow(workflow, inputs={})
    # Workflow completed despite the broken start hook
    assert result is not None
    # The well-behaved hook's start + end both fired
    assert len(end_hook.start_calls) == 1
    assert len(end_hook.end_calls) == 1


@pytest.mark.asyncio
async def test_multiple_concurrent_hooks_all_receive_dispatch():
    """Bus.run_hooks uses asyncio.gather over registered hooks. Verify
    all 3 hooks receive on_workflow_start with the same ctx — locks the
    concurrent dispatch contract so a future refactor doesn't drop one.
    """
    workflow = _make_workflow_with_bus()
    hook_a = _RecordingHook()
    hook_a.name = "a"
    hook_b = _RecordingHook()
    hook_b.name = "b"
    hook_c = _RecordingHook()
    hook_c.name = "c"
    workflow._event_bus.register(hook_a)
    workflow._event_bus.register(hook_b)
    workflow._event_bus.register(hook_c)

    from harness.core.workflow_runtime import arun_workflow

    await arun_workflow(workflow, inputs={"task": "broadcast"})

    # Each hook received the SAME workflow_id (proves ctx isn't being
    # mutated between dispatches).
    for h in (hook_a, hook_b, hook_c):
        assert len(h.start_calls) == 1
        assert h.start_calls[0].workflow_id == "test_wf"
        assert h.start_calls[0].inputs == {"task": "broadcast"}
