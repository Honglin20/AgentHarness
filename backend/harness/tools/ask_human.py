"""Ask human tool for human-in-the-loop interactions."""

from asyncio import Lock, get_event_loop
from typing import Any, Literal

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory


# Global pending questions: question_id -> Future
_pending: dict[str, Any] = {}
_lock = None


def get_lock():
    """Get the lock for _pending dict."""
    global _lock
    if _lock is None:
        _lock = Lock()
    return _lock


async def resolve_question(question_id: str, answer: str) -> None:
    """Resolve a pending ask_human question with the user's answer.

    This is called by the WebSocket handler when it receives a chat.answer event.
    """
    lock = get_lock()
    async with lock:
        future = _pending.pop(question_id, None)
        if future and not future.done():
            future.set_result(answer)


class AskHumanToolFactory(ToolFactory):
    """ask_human 工具 — agent 向用户提问并等待回答。"""

    name = "ask_human"
    description = (
        "Ask the user a question and wait for their response. "
        "Use when you need clarification, confirmation, or input from the user. "
        "The user's response will be returned to you as plain text."
    )

    def __init__(self, event_bus: Any | None = None):
        self.event_bus = event_bus

    def create(self) -> PydanticAITool:
        bus = self.event_bus

        async def ask_human(ctx: RunContext, question: str) -> str:
            import uuid

            question_id = str(uuid.uuid4())
            loop = get_event_loop()
            future = loop.create_future()

            # Store the Future
            lock = get_lock()
            async with lock:
                _pending[question_id] = future

            # Emit chat.question event via EventBus
            if bus:
                bus.emit("chat.question", {
                    "node_id": ctx.deps.agent_name,
                    "agent_name": ctx.deps.agent_name,
                    "question_id": question_id,
                    "question": question,
                })

            # Wait for response (with timeout)
            from asyncio import wait_for, TimeoutError
            try:
                answer = await wait_for(future, timeout=300.0)  # 5 minutes
                return answer
            except TimeoutError:
                return "User disconnected. Proceed with your best judgment."

        return PydanticAITool(ask_human, takes_ctx=True)