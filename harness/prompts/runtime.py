"""Dynamic runtime-status system-prompt layer.

Registered on each agent via ``@agent.system_prompt(dynamic=True)``. pydantic-ai
calls it BEFORE EVERY model request and, on subsequent turns, re-evaluates it
in place (the produced SystemPromptPart carries a ``dynamic_ref`` so it is
REPLACED rather than appended — unlike the old TodoReminderTracker which
accumulated one reminder per turn).

Two pieces of runtime context are surfaced:

  - todo progress: whether a plan exists, how many steps are done, what is
    in_progress. This replaces TodoReminderTracker's counter-based nudges
    with continuous, accurate status.
  - last tool failure: if a tool recorded a failure (via
    ``ctx.deps.last_tool_failure``) since the last request, surface it so the
    model can adapt (split a timed-out command, change a grep pattern, …).
    Cleared after surfacing so stale errors do not persist.

The function is PURE w.r.t. deps state: it reads and returns a string; it
only mutates ``last_tool_failure`` to clear a surfaced error (documented
side effect — without it the same failure would recur every turn).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from harness.tools.deps import AgentDeps
from harness.tools.todo import get_todo_state

if TYPE_CHECKING:
    pass  # typing-only imports would go here


def _todo_status_block(state) -> str:
    """Render the todo-progress portion of the runtime status.

    Returns "" when there is nothing actionable (plan complete, all done) so
    the dynamic prompt stays quiet once the agent is behaving correctly.
    """
    if state is None or not state.has_plan:
        return (
            "<runtime-status>\n"
            "Todo: no plan yet. Your first action must be "
            "TodoTool(op='create', ...) — see Base Working Norms.\n"
            "</runtime-status>"
        )

    total = len(state.steps)
    done = sum(1 for s in state.steps if s.status in ("completed", "skipped"))
    in_progress = [s for s in state.steps if s.status == "in_progress"]
    pending = [s for s in state.steps if s.status == "pending"]

    if not in_progress and not pending:
        # All terminal — nothing to nudge about. Stay quiet.
        return ""

    lines = [f"<runtime-status>", f"Todo: {done}/{total} steps done."]
    if in_progress:
        lines.append(f"In progress: {in_progress[0].content}")
    if pending:
        names = ", ".join(s.content for s in pending[:3])
        more = f" (+{len(pending)-3} more)" if len(pending) > 3 else ""
        lines.append(f"Not started: {names}{more}")
    lines.append("</runtime-status>")
    return "\n".join(lines)


def _failure_block(deps: AgentDeps) -> str:
    """Render the last-tool-failure portion, clearing it after surfacing.

    Returns "" when there is no recent failure. The deps mutation (clearing
    last_tool_failure) is the documented side effect that prevents the same
    failure from being re-surfaced every turn.
    """
    failure = deps.last_tool_failure
    if not failure:
        return ""
    tool = failure.get("tool", "a tool")
    error = str(failure.get("error", ""))[:200]
    hint = failure.get("hint", "")
    deps.last_tool_failure = None  # one-shot: surface once, then clear
    parts = [
        "<runtime-status>",
        f"Last call to {tool} failed: {error}",
    ]
    if hint:
        parts.append(f"Suggestion: {hint}")
    parts.append("</runtime-status>")
    return "\n".join(parts)


async def runtime_status(ctx: RunContext[AgentDeps]) -> str:
    """Dynamic system-prompt function: todo progress + recent tool failure.

    Called by pydantic-ai before every model request. The returned string is
    wrapped in a ``SystemPromptPart`` with ``dynamic_ref`` so on subsequent
    turns it is REPLACED in place (not appended) — this is the key property
    that distinguishes it from the legacy TodoReminderTracker.
    """
    deps = ctx.deps
    if not isinstance(deps, AgentDeps):
        # Defensive: tests / non-standard setups may pass bare deps. Staying
        # silent (no status) is safe — the agent still has its static prompt.
        return ""

    blocks = [
        b for b in (
            _todo_status_block(get_todo_state(deps)),
            _failure_block(deps),
        )
        if b
    ]
    return "\n".join(blocks)
