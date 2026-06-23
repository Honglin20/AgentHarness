"""feedback.py golden-string tests.

Originally (TASK 2 of the refactor) these asserted byte-identical reproduction
of the legacy inline wording — a pure-move contract. TASK 3 of the refinement
plan UNIFIED the language to English, deliberately changing the wording. The
golden strings below are the CURRENT English contract; they are frozen going
forward until another deliberate language/wording change.

If a function's output drifts from its golden string, the move was not pure.
"""
from __future__ import annotations

import json
import re

from harness.prompts import feedback

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


# --- step_gate.py gate-1 ---
def test_todo_not_created_msg_is_english_and_enforces():
    golden = (
        "You MUST first call TodoTool(op='create', ...) to plan your steps, "
        "listing every task you intend to complete (even for single-step tasks), "
        "before you can start executing.\n"
        "Example: TodoTool(op='create', items=[TodoItem(content='...', activeForm='...')])"
    )
    assert feedback.todo_not_created_msg() == golden
    assert "MUST" in feedback.todo_not_created_msg()  # enforcement strength preserved
    assert not _CJK_RE.search(feedback.todo_not_created_msg())


# --- step_gate.py gate-2 ---
def test_todo_not_terminal_msg_is_english():
    descriptors = ["'read auth.py'(status=pending)", "'write tests'(status=in_progress)"]
    names = ", ".join(descriptors)
    golden = (
        f"The following steps are not yet closed out: {names}.\n"
        f"Close them with one of:\n"
        f"  - TodoTool(op='complete_remaining', status='completed'|'skipped', reason='...') "
        f"to bulk-finish (use when the goal was already achieved early), or\n"
        f"  - TodoTool(op='update', task_id='...', status='completed'|'skipped') to close one step.\n"
        f"Leaving steps in pending/in_progress state is not allowed."
    )
    assert feedback.todo_not_terminal_msg(descriptors) == golden
    assert not _CJK_RE.search(feedback.todo_not_terminal_msg(descriptors))


def test_todo_not_terminal_msg_empty_list():
    out = feedback.todo_not_terminal_msg([])
    assert "The following steps are not yet closed out: ." in out
    assert not _CJK_RE.search(out)


# --- llm_executor.py schema-retry (was already English; unchanged) ---
def test_schema_retry_msg_matches_legacy():
    tool_name = "final_result"
    schema_json = json.dumps(
        {"properties": {"summary": {"type": "string"}}, "required": ["summary"]},
        indent=2, ensure_ascii=False,
    )
    legacy = (
        "## Output rejected — please retry correctly\n"
        "Your previous response did not match the required output schema. "
        f"You MUST call the `{tool_name}` tool with arguments matching this JSON schema:\n\n"
        + schema_json
        + "\n\nDo NOT emit the schema as plain text or markdown. Switch to a "
        f"`{tool_name}` tool call now and fill every required field with concrete values."
    )
    assert feedback.schema_retry_msg(tool_name, schema_json) == legacy


# --- todo nudges (now English) ---
def test_reminder_create_msg_is_english():
    out = feedback.reminder_create_msg()
    golden = (
        "<system-reminder>"
        "You have not created any task steps yet. **You MUST call the TodoTool** "
        "(op='create', items=[{content, activeForm}, ...]). "
        "**Do NOT use bash/Write/echo to write todo*.json or todo_plan*.json as a substitute** — "
        "TodoTool is a tool call, not a file write.\n"
        "Schema note: activeForm is the present-continuous description (e.g. 'Analyzing project structure'); "
        "it is **not** the status field — status is managed by the framework automatically."
        "</system-reminder>"
    )
    assert out == golden
    assert "MUST" in out
    assert not _CJK_RE.search(out)


def test_reminder_update_active_msg_is_english():
    content = "Analyzing project structure"
    task_id = "t_2"
    out = feedback.reminder_update_active_msg(content, task_id)
    golden = (
        f"<system-reminder>"
        f"You have not updated task status in a while. Currently in_progress: '{content}'. "
        f"If this stage is done, call TodoTool(op='update', task_id='{task_id}', status='completed'); "
        f"if still working, you may ignore this nudge — no need to update detail mid-step."
        f"</system-reminder>"
    )
    assert out == golden
    assert not _CJK_RE.search(out)


def test_reminder_update_idle_msg_is_english():
    out = feedback.reminder_update_idle_msg()
    golden = (
        "<system-reminder>"
        "You have not updated task status in a while. If the current stage is done, "
        "call TodoTool(op='update', ..., status='completed'); if still working, you may ignore this nudge."
        "</system-reminder>"
    )
    assert out == golden
    assert not _CJK_RE.search(out)


# --- TASK 3 contract: ALL feedback is English-only ---
def test_all_feedback_functions_are_cjk_free():
    """TASK 3 acceptance: no feedback function returns CJK characters."""
    samples = {
        "todo_not_created_msg": feedback.todo_not_created_msg(),
        "todo_not_terminal_msg": feedback.todo_not_terminal_msg(["'x'(status=pending)"]),
        "schema_retry_msg": feedback.schema_retry_msg("final_result", "{}"),
        "reminder_create_msg": feedback.reminder_create_msg(),
        "reminder_update_active_msg": feedback.reminder_update_active_msg("c", "t1"),
        "reminder_update_idle_msg": feedback.reminder_update_idle_msg(),
    }
    offenders = [name for name, s in samples.items() if _CJK_RE.search(s)]
    assert not offenders, f"feedback still contains CJK: {offenders}"
