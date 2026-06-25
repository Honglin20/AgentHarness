"""Unified error/feedback message sources for the LLM.

Centralizes the wording of every message the framework sends BACK to the
model when something went wrong (schema rejection, todo-gate violation).
Previously these strings were inlined in two places that described the
same underlying contract with subtly different wording:

  - harness/engine/step_gate.py         (todo completion gate, ModelRetry)
  - harness/engine/llm_executor.py      (schema-retry SystemPromptPart)

TASK 2 of the refactor is a pure move: every function here returns
byte-identical text to the site it replaced. TASK 3 of the refinement
plan later UNIFIED the language to English (the refactor preserved mixed
zh/en only to keep its byte-for-byte contract). The golden fixtures in
``tests/test_prompt_feedback.py`` were updated at that point to the
English wording — they are the current contract.

Note: the legacy ``todo_reminder.py`` <system-reminder> nudges
(``reminder_create_msg`` / ``reminder_update_active_msg`` /
``reminder_update_idle_msg``) were removed alongside the
``TodoReminderTracker`` class in TASK 4. Their job is now done by the
dynamic ``runtime_status`` layer (``harness/prompts/runtime.py``), which
surfaces todo progress every turn via a ``SystemPromptPart`` that is
replaced in place rather than appended — so the per-turn nudges no longer
need dedicated message functions.

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
