"""Step completion gate — pydantic-ai output validator.

Enforces the agent ↔ TODO contract:
1. Every agent MUST call ``TodoTool op='create'`` before producing output.
2. All steps MUST be in terminal state (completed/skipped) at output time.

On violation, raises :class:`ModelRetry`. pydantic-ai continues ``iter()``
with the retry prompt appended to ``message_history`` (does NOT restart,
so all prior tool calls / results are preserved — see ADR
``docs/plans/2026-06-10-todo-step-gate-adr.md``). After ``output_retries``
budget exhausted, pydantic-ai raises ``UnexpectedModelBehavior`` which
``node_factory``'s ``except`` converts to ``node.failed``.

Spike validation: ``.spike_model_retry.py`` confirms iter() + node.stream()
path triggers retry correctly. ``agent.run_stream()`` does NOT support
retry — ADR prohibition.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai.exceptions import ModelRetry

from harness.prompts import feedback
from harness.tools.deps import AgentDeps
from harness.tools.todo import get_todo_state

logger = logging.getLogger(__name__)


async def step_gate_validator(ctx: Any, data: Any) -> Any:
    """Enforce TODO step completion contract on agent output.

    Args:
        ctx: pydantic-ai RunContext; ``ctx.deps`` must be :class:`AgentDeps`
            with ``_todo_state`` extra attached (lazily created by the todo
            tool itself, so missing state means agent never called create).
        data: validated output (already passed pydantic schema validation).

    Returns:
        ``data`` unchanged on success (pass-through validator).

    Raises:
        ModelRetry: when ``has_plan`` is False or any non-terminal step exists.
    """
    deps = getattr(ctx, "deps", None)
    if not isinstance(deps, AgentDeps):
        # Not our deps type (e.g. unit tests with bare deps). Fail loud via
        # log so silent bypass is observable — ADR allows this for test
        # scaffolding, but production paths always pass AgentDeps via
        # micro_agent.create() → LLMClient.agent(deps_type=AgentDeps).
        logger.warning(
            "step_gate skipped: ctx.deps is not AgentDeps (got %s). "
            "Production agents must use AgentDeps; tests may bypass.",
            type(deps).__name__ if deps is not None else "None",
        )
        return data

    todo_state = get_todo_state(deps)

    # Gate 1: agent must have called todo op='create'.
    # todo_state is None when ensure_todo_state was never invoked, which
    # happens iff the agent never called any todo op.
    if todo_state is None or not todo_state.has_plan:
        raise ModelRetry(feedback.todo_not_created_msg())

    # Gate 2: all steps must be terminal (completed or skipped).
    non_terminal = [
        s for s in todo_state.steps
        if s.status in ("pending", "in_progress")
    ]
    if non_terminal:
        descriptors = (
            f"'{s.content}'(status={s.status})" for s in non_terminal
        )
        raise ModelRetry(feedback.todo_not_terminal_msg(descriptors))

    return data
