"""todo tool — agent-driven step planning and progress tracking.

Agents create their own step lists via op='create', update progress via
op='update', and list current state via op='list'.  The framework emits
events for real-time frontend rendering and auto-advances to the next
pending step when a step is completed.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory

logger = logging.getLogger(__name__)

# Key used to store TodoState on AgentDeps (which has extra="allow").
DEPS_TODO_KEY = "_todo_state"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class TodoItem(BaseModel):
    content: str = Field(..., description="Step description (imperative, e.g. 'Analyze project structure')")
    activeForm: str = Field(..., description="Present-continuous form (e.g. 'Analyzing project structure...')")


class StepEntry(BaseModel):
    task_id: str
    content: str
    activeForm: str
    status: Literal["pending", "in_progress", "completed"] = "pending"
    detail: str | None = None


class TodoState:
    """Per-node TODO state.

    Stored on AgentDeps via the ``_todo_state`` extra field so each node
    gets its own isolated state without touching the shared ToolRegistry.
    """

    def __init__(self) -> None:
        self.steps: list[StepEntry] = []
        self.has_plan: bool = False
        self._counter: int = 0

    def next_task_id(self) -> str:
        self._counter += 1
        return f"t_{self._counter}"


# ---------------------------------------------------------------------------
# Helper: attach / read TodoState from AgentDeps
# ---------------------------------------------------------------------------

def ensure_todo_state(deps: AgentDeps) -> TodoState:
    """Get or lazily create TodoState on AgentDeps."""
    state = getattr(deps, DEPS_TODO_KEY, None)
    if state is None:
        state = TodoState()
        setattr(deps, DEPS_TODO_KEY, state)
    return state


def get_todo_state(deps: AgentDeps) -> TodoState | None:
    return getattr(deps, DEPS_TODO_KEY, None)


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

class TodoToolFactory(ToolFactory):
    """todo — plan and track task steps."""

    name = "todo"
    description = (
        "Plan and track your task steps. "
        "You MUST call this with op='create' to define your step list BEFORE starting any work, "
        "even for single-step tasks. "
        "Update step status with op='update' as you progress. "
        "Use op='list' to view current steps."
    )

    def __init__(self, event_bus: Any | None = None):
        self.event_bus = event_bus

    def create(self) -> PydanticAITool:
        bus = self.event_bus

        async def todo(
            ctx: RunContext,
            op: Literal["create", "update", "list"],
            items: list[TodoItem] | None = None,
            task_id: str | None = None,
            status: Literal["in_progress", "completed"] | None = None,
            detail: str | None = None,
        ) -> str:
            deps = ctx.deps
            agent_name = deps.agent_name if isinstance(deps, AgentDeps) else ""
            node_id = agent_name
            workflow_id = deps.workflow_id if isinstance(deps, AgentDeps) else None

            # Lazily init per-node state on first call
            state = ensure_todo_state(deps) if isinstance(deps, AgentDeps) else None
            if state is None:
                return "Error: todo not available for this agent."

            # --- create ---
            if op == "create":
                if not items:
                    return "Error: items is required for op='create'."
                new_steps: list[StepEntry] = []
                for i, item in enumerate(items):
                    entry = StepEntry(
                        task_id=state.next_task_id(),
                        content=item.content,
                        activeForm=item.activeForm,
                        status="in_progress" if (not state.steps and i == 0) else "pending",
                    )
                    new_steps.append(entry)
                state.steps.extend(new_steps)
                state.has_plan = True

                if bus:
                    payload_created: dict[str, Any] = {
                        "node_id": node_id,
                        "agent_name": agent_name,
                        "items": [e.model_dump() for e in new_steps],
                    }
                    if workflow_id:
                        payload_created["workflow_id"] = workflow_id
                    bus.emit("todo.created", payload_created)

                first = new_steps[0]
                if len(new_steps) == 1:
                    return f"Created 1 step. '{first.content}' is now active."
                return f"Created {len(new_steps)} steps. Step 1 '{first.content}' is now active."

            # --- update ---
            if op == "update":
                if not task_id:
                    return "Error: task_id is required for op='update'."
                entry = next((s for s in state.steps if s.task_id == task_id), None)
                if not entry:
                    return f"Error: task_id '{task_id}' not found."

                auto_advance = None
                next_pending: StepEntry | None = None
                if status is not None:
                    entry.status = status
                    if status == "completed":
                        next_pending = next(
                            (s for s in state.steps if s.status == "pending"), None
                        )
                        if next_pending:
                            next_pending.status = "in_progress"
                            auto_advance = {
                                "next_task_id": next_pending.task_id,
                                "status": "in_progress",
                            }

                if detail is not None:
                    entry.detail = detail

                if bus:
                    payload_updated: dict[str, Any] = {
                        "node_id": node_id,
                        "agent_name": agent_name,
                        "task_id": entry.task_id,
                        "status": entry.status if status else None,
                        "detail": detail,
                        "auto_advance": auto_advance,
                    }
                    if workflow_id:
                        payload_updated["workflow_id"] = workflow_id
                    bus.emit("todo.updated", payload_updated)

                parts = [f"Step '{entry.content}' updated."]
                if auto_advance and next_pending:
                    parts.append(f" Auto-advanced to '{next_pending.content}'.")
                return "".join(parts)

            # --- list ---
            if op == "list":
                if not state.steps:
                    return "No steps created yet. Call todo(op='create', items=[...]) first."
                total = len(state.steps)
                symbols = {"pending": "⬜", "in_progress": "\U0001f535", "completed": "✅"}
                lines = []
                for i, s in enumerate(state.steps, 1):
                    sym = symbols.get(s.status, "⬜")
                    label = s.activeForm if s.status == "in_progress" else s.content
                    lines.append(f"[{i}/{total}] {sym} {label}")
                return "\n".join(lines)

            return f"Unknown op: {op}"

        return PydanticAITool(
            self._wrap_fn(todo, self.name),
            takes_ctx=True,
            description=self.description,
        )
