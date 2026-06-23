"""TASK 2 acceptance test: feedback.py reproduces the legacy inline wording.

Pure-move verification. Each function in harness/prompts/feedback.py must
return byte-identical text to the inline string it replaced in step_gate /
llm_executor / todo_reminder. The "legacy" strings below are copied from the
pre-refactor source (captured at TASK 2 start) — they ARE the contract.

If a function's output drifts from its golden string, the move was not pure.
"""
from __future__ import annotations

import json

from harness.prompts import feedback


# --- step_gate.py gate-1 ---
def test_todo_not_created_msg_matches_legacy():
    legacy = (
        "你必须先调用 TodoTool 工具 op='create' 规划步骤，"
        "列出所有打算完成的任务（即使是单步任务），然后才能开始执行。\n"
        "示例：TodoTool(op='create', items=[TodoItem(content='...', activeForm='...')])"
    )
    assert feedback.todo_not_created_msg() == legacy


# --- step_gate.py gate-2 ---
def test_todo_not_terminal_msg_matches_legacy():
    # Reproduce step_gate's descriptor formatting + join, then the legacy body.
    descriptors = ["'read auth.py'(status=pending)", "'write tests'(status=in_progress)"]
    legacy_names = ", ".join(descriptors)
    legacy = (
        f"以下步骤还未显式收尾: {legacy_names}。\n"
        f"请调用以下之一收尾：\n"
        f"  - TodoTool(op='complete_remaining', status='completed'|'skipped', reason='...') "
        f"批量收尾（用于目标已提前达成的场景），或\n"
        f"  - TodoTool(op='update', task_id='...', status='completed'|'skipped') 单步收尾\n"
        f"注意：不允许遗留 pending/in_progress 状态的步骤。"
    )
    assert feedback.todo_not_terminal_msg(descriptors) == legacy


def test_todo_not_terminal_msg_empty_list():
    # Edge: no descriptors → ", ".join([]) == "" → message still well-formed.
    out = feedback.todo_not_terminal_msg([])
    assert "以下步骤还未显式收尾: 。" in out


# --- llm_executor.py schema-retry ---
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


# --- todo_reminder.py create nudge ---
def test_reminder_create_msg_matches_legacy():
    legacy = (
        "<system-reminder>"
        "你还没有创建任务步骤。**必须调用 TodoTool 工具** "
        "(op='create', items=[{content, activeForm}, ...])，"
        "**禁止用 bash/Write/echo 写 todo*.json 或 todo_plan*.json 来替代** —— "
        "TodoTool 是工具调用，不是文件写入。\n"
        "schema 提醒：activeForm 是现在进行时描述（如 'Analyzing project structure'），"
        "**不是** status 字段；status 由框架自动管理。"
        "</system-reminder>"
    )
    assert feedback.reminder_create_msg() == legacy


# --- todo_reminder.py update-active nudge ---
def test_reminder_update_active_msg_matches_legacy():
    content = "Analyzing project structure"
    task_id = "t_2"
    legacy = (
        f"<system-reminder>"
        f"你有一段时间没更新 task 状态了。当前 in_progress: 「{content}」。"
        f"如果这个 stage 已完成，调用 TodoTool(op='update', task_id='{task_id}', status='completed')；"
        f"如果还在做，可以忽略此提醒，不需要中途更新 detail。"
        f"</system-reminder>"
    )
    assert feedback.reminder_update_active_msg(content, task_id) == legacy


# --- todo_reminder.py update-idle nudge ---
def test_reminder_update_idle_msg_matches_legacy():
    legacy = (
        "<system-reminder>"
        "你有一段时间没更新 task 状态了。如果当前 stage 已完成，"
        "调用 TodoTool(op='update', ..., status='completed')；如果还在做，可以忽略此提醒。"
        "</system-reminder>"
    )
    assert feedback.reminder_update_idle_msg() == legacy
