"""Unified error/feedback message sources for the LLM.

Centralizes the wording of every message the framework sends BACK to the
model when something went wrong (schema rejection, todo-gate violation,
progress reminders). Previously these strings were inlined in three places
that described the same underlying contract with subtly different wording:

  - harness/engine/step_gate.py         (todo completion gate, ModelRetry)
  - harness/engine/llm_executor.py      (schema-retry SystemPromptPart)
  - harness/tools/todo_reminder.py      (<system-reminder> nudges)

TASK 2 is a pure move: every function here returns BYTE-IDENTICAL text to
the site it replaced. The contract is frozen by
``tests/test_prompt_feedback.py``.

TASK 3 of the refinement plan later UNIFIED the language to English (the
refactor preserved mixed zh/en only to keep its byte-for-byte contract).
The golden fixtures in ``tests/test_prompt_feedback.py`` were updated at
that point to the English wording — they are the current contract.

Design rules
------------
- Pure functions: no I/O, no side effects, no logging.
- All variability (tool names, step lists, schemas) passed as parameters.
- Language: English-only. Tool/parameter names (TodoTool, op='create') stay
  literal — the model aligns tool calls on them.
"""
from __future__ import annotations

from typing import Iterable


# ---------------------------------------------------------------------------
# step_gate.py — todo completion gate (raises ModelRetry with these).
# ---------------------------------------------------------------------------

def todo_not_created_msg() -> str:
    """Gate 1: agent never called TodoTool(op='create').

    English-only (language unified in TASK 3 of the refinement plan). Same
    enforcement strength as the prior Chinese wording.
    """
    return (
        "You MUST first call TodoTool(op='create', ...) to plan your steps, "
        "listing every task you intend to complete (even for single-step tasks), "
        "before you can start executing.\n"
        "Example: TodoTool(op='create', items=[TodoItem(content='...', activeForm='...')])"
    )


def todo_not_terminal_msg(non_terminal_descriptors: Iterable[str]) -> str:
    """Gate 2: some steps are still pending/in_progress at output time.

    ``non_terminal_descriptors`` are pre-formatted per-step strings like
    ``"'<content>'(status=<status>)"`` — step_gate builds these from
    StepEntry fields so this function stays free of step-shape knowledge.
    """
    names = ", ".join(non_terminal_descriptors)
    return (
        f"The following steps are not yet closed out: {names}.\n"
        f"Close them with one of:\n"
        f"  - TodoTool(op='complete_remaining', status='completed'|'skipped', reason='...') "
        f"to bulk-finish (use when the goal was already achieved early), or\n"
        f"  - TodoTool(op='update', task_id='...', status='completed'|'skipped') to close one step.\n"
        f"Leaving steps in pending/in_progress state is not allowed."
    )


# ---------------------------------------------------------------------------
# llm_executor.py — schema-rejection retry reminder.
# ---------------------------------------------------------------------------

def schema_retry_msg(tool_name: str, schema_json: str) -> str:
    """Reminder appended when the previous output failed schema validation.

    ``schema_json`` must be the pre-formatted, indent=2 JSON string of the
    stripped schema (caller handles strip_schema + json.dumps so this
    function has no formatting dependency).

    Byte-identical to llm_executor.py:154-161 given the same inputs.
    """
    return (
        "## Output rejected — please retry correctly\n"
        "Your previous response did not match the required output schema. "
        f"You MUST call the `{tool_name}` tool with arguments matching this JSON schema:\n\n"
        + schema_json
        + "\n\nDo NOT emit the schema as plain text or markdown. Switch to a "
        f"`{tool_name}` tool call now and fill every required field with concrete values."
    )


# ---------------------------------------------------------------------------
# todo_reminder.py — <system-reminder> nudges (text moved here in TASK 2;
# the tracker class itself is removed in TASK 4 when the dynamic layer
# replaces it).
# ---------------------------------------------------------------------------

def reminder_create_msg() -> str:
    """Nudge: agent hasn't created a todo plan yet.

    English-only (language unified in TASK 3). The <system-reminder> wrapper
    is a rendering convention, not language — kept as-is.
    """
    return (
        "<system-reminder>"
        "You have not created any task steps yet. **You MUST call the TodoTool** "
        "(op='create', items=[{content, activeForm}, ...]). "
        "**Do NOT use bash/Write/echo to write todo*.json or todo_plan*.json as a substitute** — "
        "TodoTool is a tool call, not a file write.\n"
        "Schema note: activeForm is the present-continuous description (e.g. 'Analyzing project structure'); "
        "it is **not** the status field — status is managed by the framework automatically."
        "</system-reminder>"
    )


def reminder_update_active_msg(content: str, task_id: str) -> str:
    """Nudge: plan exists, an in_progress step hasn't been updated."""
    return (
        f"<system-reminder>"
        f"You have not updated task status in a while. Currently in_progress: '{content}'. "
        f"If this stage is done, call TodoTool(op='update', task_id='{task_id}', status='completed'); "
        f"if still working, you may ignore this nudge — no need to update detail mid-step."
        f"</system-reminder>"
    )


def reminder_update_idle_msg() -> str:
    """Nudge: plan exists, no in_progress step, but no recent update."""
    return (
        "<system-reminder>"
        "You have not updated task status in a while. If the current stage is done, "
        "call TodoTool(op='update', ..., status='completed'); if still working, you may ignore this nudge."
        "</system-reminder>"
    )
