"""Dynamic runtime-status system-prompt layer.

Registered on each agent via ``@agent.system_prompt(dynamic=True)``. pydantic-ai
calls it BEFORE EVERY model request and, on subsequent turns, re-evaluates it
in place (the produced SystemPromptPart carries a ``dynamic_ref`` so it is
REPLACED rather than appended — unlike the old TodoReminderTracker which
accumulated one reminder per turn).

Four pieces of runtime context are surfaced:

  - todo progress: whether a plan exists, how many steps are done, what is
    in_progress. This replaces TodoReminderTracker's counter-based nudges
    with continuous, accurate status.
  - node iteration: when a node re-enters (loop/retry, iteration > 1), nudge
    the model to vary its approach rather than repeat an identical attempt.
  - last tool failure: if a tool recorded a failure (via
    ``ctx.deps.last_tool_failure``) since the last request, surface it so the
    model can adapt (split a timed-out command, change a grep pattern, …).
    Cleared after surfacing so stale errors do not persist.
  - generic reminders: any module may append to ``deps.pending_reminders``
    to surface a transient condition (file changed since last read, duplicate
    tool call, ...). Flushed each turn into a Reminders block, then cleared.
    This is the OCP channel for ad-hoc reminders that don't warrant their own
    structured field (mirrors Claude Code's <system-reminder> semantics).

The function is PURE w.r.t. deps state: it reads and returns a string; it
only mutates the one-shot queues (``last_tool_failure`` and
``pending_reminders``) to clear surfaced entries (documented side effect —
without it the same item would recur every turn).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from harness.tools.deps import AgentDeps
from harness.tools.todo import get_todo_state

if TYPE_CHECKING:
    pass  # typing-only imports would go here


def _todo_status_block(state, *, enabled: bool) -> str:
    """Render the todo-progress portion of the runtime status.

    Returns "" when TodoTool is not loaded (enabled=False), or when there is
    nothing actionable (plan complete, all done).
    """
    if not enabled:
        return ""

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


def _iteration_block(deps: AgentDeps) -> str:
    """Render the node-iteration portion of the runtime status.

    ``deps.iteration`` is the node-level invocation counter (1-indexed, bumped
    each time this node re-runs via a conditional-edge loop or retry). Stays
    quiet on the first invocation (iteration <= 1) so single-shot agents get
    no noise; surfaces from the second onward so the model can tell it is
    re-entering and should converge rather than repeat an identical attempt.

    Pure read of deps.iteration — no mutation, no other state.
    """
    it = getattr(deps, "iteration", 1) or 1
    if it <= 1:
        return ""
    return (
        "<runtime-status>\n"
        f"Iteration: {it} of this node — if a prior attempt did not succeed, "
        f"vary your approach rather than repeating it verbatim.\n"
        "</runtime-status>"
    )


# Cap on how many reminders a single turn surfaces. Prevents a runaway
# producer from flooding the system prompt. Extras are dropped (the queue is
# still cleared) — surfacing the first N is enough to flag the situation.
_REMINDER_CAP = 5


def _reminders_block(deps: AgentDeps) -> str:
    """Render the generic one-shot reminder queue, flushing it after surfacing.

    Any module may append short strings to ``deps.pending_reminders`` when it
    observes a transient condition worth surfacing (file changed since last
    read, duplicate tool call, ...). This block flushes the queue into a
    <runtime-status> Reminders section each turn, then CLEARS it — reminders
    are one-shot (surfaced once, not re-surfaced every turn). This mirrors
    Claude Code's <system-reminder> semantics.

    The clear is the documented side effect: without it, a stale reminder
    would recur every turn. Capped at _REMINDER_CAP entries per turn.
    """
    reminders = deps.pending_reminders
    if not reminders:
        return ""
    shown = reminders[:_REMINDER_CAP]
    dropped = len(reminders) - len(shown)
    deps.pending_reminders = []  # flush: one-shot, then clear
    lines = ["<runtime-status>", "Reminders:"]
    lines.extend(f"- {r}" for r in shown)
    if dropped > 0:
        lines.append(f"- (+{dropped} more reminder(s) dropped this turn)")
    lines.append("</runtime-status>")
    return "\n".join(lines)


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

    todo_enabled = getattr(deps, "_todo_enabled", False)
    blocks = [
        b for b in (
            _todo_status_block(get_todo_state(deps), enabled=todo_enabled),
            _iteration_block(deps),
            _failure_block(deps),
            _reminders_block(deps),
        )
        if b
    ]
    return "\n".join(blocks)
