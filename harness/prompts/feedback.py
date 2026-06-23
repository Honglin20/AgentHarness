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
``tests/test_prompt_feedback.py``. Do not "improve" wording without
deliberately updating both the function and its golden fixture.

Design rules
------------
- Pure functions: no I/O, no side effects, no logging.
- All variability (tool names, step lists, schemas) passed as parameters.
- Language: preserved as-is (mixed zh/en) per the refactor scope — language
  normalization is explicitly OUT OF SCOPE for this refactor.
"""
from __future__ import annotations

from typing import Iterable


# ---------------------------------------------------------------------------
# step_gate.py — todo completion gate (raises ModelRetry with these).
# ---------------------------------------------------------------------------

def todo_not_created_msg() -> str:
    """Gate 1: agent never called TodoTool(op='create').

    Byte-identical to step_gate.py:66-70.
    """
    return (
        "你必须先调用 TodoTool 工具 op='create' 规划步骤，"
        "列出所有打算完成的任务（即使是单步任务），然后才能开始执行。\n"
        "示例：TodoTool(op='create', items=[TodoItem(content='...', activeForm='...')])"
    )


def todo_not_terminal_msg(non_terminal_descriptors: Iterable[str]) -> str:
    """Gate 2: some steps are still pending/in_progress at output time.

    ``non_terminal_descriptors`` are pre-formatted per-step strings like
    ``"'<content>'(status=<status>)"`` — step_gate builds these from
    StepEntry fields so this function stays free of step-shape knowledge.

    Byte-identical to step_gate.py:81-88 given the same descriptors.
    """
    names = ", ".join(non_terminal_descriptors)
    return (
        f"以下步骤还未显式收尾: {names}。\n"
        f"请调用以下之一收尾：\n"
        f"  - TodoTool(op='complete_remaining', status='completed'|'skipped', reason='...') "
        f"批量收尾（用于目标已提前达成的场景），或\n"
        f"  - TodoTool(op='update', task_id='...', status='completed'|'skipped') 单步收尾\n"
        f"注意：不允许遗留 pending/in_progress 状态的步骤。"
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

    Byte-identical to todo_reminder.py:49-56 (including the wrapping tags).
    """
    return (
        "<system-reminder>"
        "你还没有创建任务步骤。**必须调用 TodoTool 工具** "
        "(op='create', items=[{content, activeForm}, ...])，"
        "**禁止用 bash/Write/echo 写 todo*.json 或 todo_plan*.json 来替代** —— "
        "TodoTool 是工具调用，不是文件写入。\n"
        "schema 提醒：activeForm 是现在进行时描述（如 'Analyzing project structure'），"
        "**不是** status 字段；status 由框架自动管理。"
        "</system-reminder>"
    )


def reminder_update_active_msg(content: str, task_id: str) -> str:
    """Nudge: plan exists, an in_progress step hasn't been updated.

    Byte-identical to todo_reminder.py:68-72 given the same step fields.
    """
    return (
        f"<system-reminder>"
        f"你有一段时间没更新 task 状态了。当前 in_progress: 「{content}」。"
        f"如果这个 stage 已完成，调用 TodoTool(op='update', task_id='{task_id}', status='completed')；"
        f"如果还在做，可以忽略此提醒，不需要中途更新 detail。"
        f"</system-reminder>"
    )


def reminder_update_idle_msg() -> str:
    """Nudge: plan exists, no in_progress step, but no recent update.

    Byte-identical to todo_reminder.py:75-78.
    """
    return (
        "<system-reminder>"
        "你有一段时间没更新 task 状态了。如果当前 stage 已完成，"
        "调用 TodoTool(op='update', ..., status='completed')；如果还在做，可以忽略此提醒。"
        "</system-reminder>"
    )
