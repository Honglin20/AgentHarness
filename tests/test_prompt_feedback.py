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


# --- TASK 3 contract: ALL feedback is English-only ---
def test_all_feedback_functions_are_cjk_free():
    """TASK 3 acceptance: no feedback function returns CJK characters."""
    samples = {
        "todo_not_created_msg": feedback.todo_not_created_msg(),
        "todo_not_terminal_msg": feedback.todo_not_terminal_msg(["'x'(status=pending)"]),
        "schema_retry_msg": feedback.schema_retry_msg("final_result", "{}"),
    }
    offenders = [name for name, s in samples.items() if _CJK_RE.search(s)]
    assert not offenders, f"feedback still contains CJK: {offenders}"
