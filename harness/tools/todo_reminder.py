"""TodoReminderTracker — injects <system-reminder> when agent forgets to update todos.

Tracks tool-call frequency independently of TodoState. TodoState is only
read when generating the reminder text (to include step-specific details).
If the agent never calls the todo tool, the CREATE reminder still fires.
"""

from __future__ import annotations

from harness.tools.deps import AgentDeps
from harness.tools.todo import get_todo_state


class TodoReminderTracker:
    """Track tool-call frequency and generate <system-reminder> injections.

    Two thresholds:
      - CREATE: If agent hasn't called TodoTool(op='create') after N non-todo calls,
        remind it to plan first.
      - UPDATE: If agent has a plan but hasn't called TodoTool(op='update') after N
        non-todo calls, remind it to update progress.

    The counter is maintained internally — it does NOT depend on TodoState
    existing. This ensures the CREATE reminder fires even before the agent
    has ever called the todo tool.
    """

    CREATE_THRESHOLD = 1
    UPDATE_THRESHOLD = 10

    def __init__(self, deps: AgentDeps) -> None:
        self._deps = deps
        self._non_todo_calls: int = 0

    def on_tool_call(self, tool_name: str) -> None:
        if tool_name == "TodoTool":
            self._non_todo_calls = 0
        else:
            self._non_todo_calls += 1

    def get_reminder(self) -> str | None:
        state = get_todo_state(self._deps)

        # --- No plan yet: remind to create one ---
        if state is None or not state.has_plan:
            if self._non_todo_calls >= self.CREATE_THRESHOLD:
                self._non_todo_calls = 0
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
            return None

        # --- Plan exists but agent hasn't updated progress ---
        if self._non_todo_calls >= self.UPDATE_THRESHOLD:
            self._non_todo_calls = 0
            active = next(
                (step for step in state.steps if step.status == "in_progress"), None
            )
            if active:
                return (
                    f"<system-reminder>"
                    f"你有一段时间没更新 task 状态了。当前 in_progress: 「{active.content}」。"
                    f"如果这个 stage 已完成，调用 TodoTool(op='update', task_id='{active.task_id}', status='completed')；"
                    f"如果还在做，可以忽略此提醒，不需要中途更新 detail。"
                    f"</system-reminder>"
                )
            return (
                "<system-reminder>"
                "你有一段时间没更新 task 状态了。如果当前 stage 已完成，"
                "调用 TodoTool(op='update', ..., status='completed')；如果还在做，可以忽略此提醒。"
                "</system-reminder>"
            )

        return None
