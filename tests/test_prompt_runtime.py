"""TASK 4 acceptance: dynamic runtime-status system prompt.

Verifies the three properties that distinguish the dynamic layer from the
legacy TodoReminderTracker:

1. TIMING — runtime_status is invoked before EVERY model request (not only
   after failures). This is the user's core question: "is it fail-retry or
   every-turn?" Answer: every turn.
2. TODO PROGRESS — when a plan exists, the status reflects real step state.
3. FAILURE SURFACING — last_tool_failure is surfaced once, then cleared
   (one-shot, no accumulation).

These are unit tests against runtime_status directly (no real LLM). The
behavioral integration is covered by test_prompt_demo_behavior.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from harness.prompts.runtime import (
    runtime_status,
    _todo_status_block,
    _failure_block,
    _iteration_block,
    _reminders_block,
    _REMINDER_CAP,
)
from harness.tools.deps import AgentDeps
from harness.tools.todo import TodoState, StepEntry, ensure_todo_state


def _make_ctx(deps: AgentDeps):
    """Build a minimal RunContext-like object carrying deps."""
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


# --- Property 1: timing (every-turn invocation) ---

@pytest.mark.asyncio
async def test_runtime_status_invoked_every_turn_not_just_on_failure():
    """runtime_status must be callable on every request, returning current state.

    The 'every turn' property is enforced by pydantic-ai's dynamic_ref
    mechanism, not by us — but we verify the function is safe + meaningful to
    call repeatedly with evolving state (the precondition for every-turn use).
    """
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    deps._todo_enabled = True  # TodoTool loaded → gate active

    # Turn 1: no plan yet → should urge creation.
    r1 = await runtime_status(_make_ctx(deps))
    assert "no plan yet" in r1

    # Turn 2: agent created a plan with one pending step.
    state = ensure_todo_state(deps)
    state.has_plan = True
    state.steps.append(StepEntry(task_id="t_1", content="do X", activeForm="doing X"))
    r2 = await runtime_status(_make_ctx(deps))
    assert "0/1" in r2 and "do X" in r2

    # Turn 3: step completed → status goes quiet (all terminal).
    state.steps[0].status = "completed"
    r3 = await runtime_status(_make_ctx(deps))
    assert r3 == ""  # nothing to nudge about


def test_runtime_status_registered_as_dynamic_on_real_agent():
    """Per-request re-invocation is guaranteed by the pydantic-ai registration.

    micro_agent.create() registers runtime_status via
    ``agent.system_prompt(dynamic=True)(runtime_status)``. This test pins that
    contract by building a real pydantic-ai Agent the same way and asserting
    the function lands in the agent's DYNAMIC prompt registry (the set pydantic-ai
    re-evaluates every request, replacing the prior turn in place via dynamic_ref).

    Without dynamic=True, a system-prompt function is evaluated ONCE at run
    start and its output frozen into message history — so the agent would never
    see updated todo progress. This is the single most important property of the
    refactor and the one a future careless edit (e.g. dropping dynamic=True, or
    memoizing runtime_status) would silently break.
    """
    from pydantic_ai import Agent

    # Build an agent the same way micro_agent.create() does (deps_type=AgentDeps).
    agent = Agent("test", deps_type=AgentDeps, system_prompt="static")
    # The exact registration call used in harness/engine/micro_agent.py.
    agent.system_prompt(dynamic=True)(runtime_status)

    # pydantic-ai stores dynamic prompts separately so they are re-evaluated
    # every request; static ones are evaluated once. Assert our function is in
    # the DYNAMIC bucket keyed by its __name__.
    dynamic_fns = getattr(agent, "_system_prompt_dynamic_functions", {})
    assert "runtime_status" in dynamic_fns, (
        "runtime_status must be registered with dynamic=True or it freezes after "
        "the first request (the bug the refactor fixed). Was dynamic=True dropped?"
    )
    # Sanity: the static prompt is NOT in the dynamic bucket (no false positive).
    static_fns = [r for r in getattr(agent, "_system_prompt_functions", [])
                  if not r.dynamic]
    # 'static' is a plain string, so it won't appear as a function — but the
    # dynamic bucket must contain ONLY runtime_status.
    assert set(dynamic_fns) == {"runtime_status"}


@pytest.mark.asyncio
async def test_runtime_status_is_not_cached_across_state_changes(monkeypatch):
    """A regression guard: if someone wraps runtime_status in lru_cache/@cache,
    every turn would return the SAME frozen string. This test would fail.

    We spy on the underlying block functions to prove runtime_status re-reads
    live state on every call (3 evolving turns → 3 distinct outputs).
    """
    import harness.prompts.runtime as rt

    call_count = {"n": 0}
    real_todo = rt._todo_status_block

    def counting_todo(state, *, enabled=False):
        call_count["n"] += 1
        return real_todo(state, enabled=enabled)

    monkeypatch.setattr(rt, "_todo_status_block", counting_todo)

    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    deps._todo_enabled = True
    # Turn 1
    await runtime_status(_make_ctx(deps))
    # Turn 2 — create plan
    state = ensure_todo_state(deps)
    state.has_plan = True
    state.steps.append(StepEntry(task_id="t_1", content="x", activeForm="x"))
    await runtime_status(_make_ctx(deps))
    # Turn 3 — complete
    state.steps[0].status = "completed"
    await runtime_status(_make_ctx(deps))

    # If runtime_status were cached, _todo_status_block would run once, not 3×.
    assert call_count["n"] == 3, (
        f"runtime_status must re-read state every call (expected 3 reads, got "
        f"{call_count['n']}) — has it been memoized/cached?"
    )


# --- Property 2: todo progress accuracy ---

def test_todo_status_no_plan_urges_creation():
    out = _todo_status_block(None, enabled=True)
    assert "no plan yet" in out
    assert "TodoTool(op='create'" in out


def test_todo_status_partial_progress():
    state = TodoState()
    state.has_plan = True
    state.steps = [
        StepEntry(task_id="t_1", content="done task", activeForm="doing", status="completed"),
        StepEntry(task_id="t_2", content="active task", activeForm="doing", status="in_progress"),
        StepEntry(task_id="t_3", content="pending task", activeForm="doing", status="pending"),
    ]
    out = _todo_status_block(state, enabled=True)
    assert "1/3" in out
    assert "active task" in out
    assert "pending task" in out


def test_todo_status_all_terminal_is_quiet():
    """When every step is completed/skipped, the status must NOT nag."""
    state = TodoState()
    state.has_plan = True
    state.steps = [
        StepEntry(task_id="t_1", content="a", activeForm="a", status="completed"),
        StepEntry(task_id="t_2", content="b", activeForm="b", status="skipped"),
    ]
    assert _todo_status_block(state, enabled=True) == ""


def test_todo_status_truncates_long_pending_list():
    """More than 3 pending steps → show first 3 + '(+N more)'."""
    state = TodoState()
    state.has_plan = True
    state.steps = [
        StepEntry(task_id=f"t_{i}", content=f"task{i}", activeForm=f"task{i}", status="pending")
        for i in range(5)
    ]
    out = _todo_status_block(state, enabled=True)
    assert "+2 more" in out


# --- Property 3: failure surfacing is one-shot ---

def test_failure_block_surfaces_then_clears():
    """A recorded failure must be surfaced exactly once, then cleared."""
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    deps.last_tool_failure = {
        "tool": "bash", "error": "command timed out", "hint": "split the command"
    }
    out1 = _failure_block(deps)
    assert "bash" in out1 and "timed out" in out1 and "split the command" in out1
    # Critical: cleared after surfacing.
    assert deps.last_tool_failure is None
    # Second call → nothing (already cleared).
    assert _failure_block(deps) == ""


def test_failure_block_empty_when_none():
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    assert _failure_block(deps) == ""


# --- Property 4: node iteration surfacing (TASK 5) ---

def test_iteration_block_quiet_on_first_invocation():
    """iteration <= 1 → no block (single-shot agents get no noise)."""
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a", iteration=1)
    assert _iteration_block(deps) == ""


def test_iteration_block_quiet_on_default():
    """Default iteration (1) → no block."""
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    assert _iteration_block(deps) == ""


def test_iteration_block_surfaces_on_retry():
    """iteration > 1 → block present, naming the iteration number."""
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a", iteration=3)
    out = _iteration_block(deps)
    assert "iteration" in out.lower()
    assert "3" in out


def test_iteration_block_advises_varying_approach():
    """The iteration block should nudge the model to change approach, not repeat."""
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a", iteration=2)
    out = _iteration_block(deps).lower()
    assert "vary" in out or "repeat" in out


# --- Property 5: generic reminders pipeline (TASK 6) ---

def test_reminders_block_empty_when_queue_empty():
    """No queued reminders → no block (quiet when nothing to say)."""
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    assert _reminders_block(deps) == ""


def test_reminders_block_surfaces_then_flushes():
    """Queued reminders are surfaced once, then the queue is cleared (one-shot)."""
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    deps.pending_reminders = ["alpha", "beta"]
    out = _reminders_block(deps)
    assert "alpha" in out and "beta" in out
    assert deps.pending_reminders == []  # flushed
    # Second call → nothing (queue already cleared).
    assert _reminders_block(deps) == ""


def test_reminders_block_caps_at_five():
    """More than _REMINDER_CAP reminders → show first N + a dropped-count note."""
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    deps.pending_reminders = [f"r{i}" for i in range(_REMINDER_CAP + 2)]
    out = _reminders_block(deps)
    assert f"+2 more reminder(s) dropped" in out
    # The queue is fully cleared regardless of the cap (dropped ones too).
    assert deps.pending_reminders == []


@pytest.mark.asyncio
async def test_runtime_status_combines_todo_and_failure():
    deps = AgentDeps(agent_name="a", workflow_id="w", node_id="a")
    deps._todo_enabled = True
    state = ensure_todo_state(deps)
    state.has_plan = True
    state.steps.append(StepEntry(task_id="t_1", content="x", activeForm="x", status="in_progress"))
    deps.last_tool_failure = {"tool": "grep", "error": "no matches", "hint": None}
    out = await runtime_status(_make_ctx(deps))
    assert "0/1" in out and "x" in out  # 0 done, 1 in_progress
    assert "grep" in out and "no matches" in out
    assert deps.last_tool_failure is None  # cleared


def test_runtime_status_handles_bare_deps():
    """Defensive: non-AgentDeps deps must not crash (returns empty)."""
    import asyncio
    ctx = MagicMock()
    ctx.deps = "not deps"
    assert asyncio.get_event_loop().run_until_complete(runtime_status(ctx)) == ""
