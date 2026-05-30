"""ask_human — deprecated alias for ask_user.

Kept as a thin shim so old workflows / WS handlers continue to work.
Prefer `harness.tools.ask_user.AskUserToolFactory` for new code.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools import _human_io
from harness.tools.ask_user import DEFAULT_TIMEOUT_SEC, TIMEOUT_MESSAGE, assemble_answer
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory


# Back-compat re-exports for callers/tests that imported these directly.
_pending = _human_io._pending  # noqa: SLF001
get_lock = _human_io._get_lock  # noqa: SLF001


async def resolve_question(question_id: str, answer: Any) -> None:
    """Legacy WS handler entry point.

    Accepts a raw string (legacy chat.answer.answer) or a dict (new
    chat.answer with selected/custom_input). Forwards to the shared
    _human_io registry.
    """
    if isinstance(answer, str):
        await _human_io.resolve(question_id, {"answer": answer})
    else:
        await _human_io.resolve(question_id, answer)


class AskHumanToolFactory(ToolFactory):
    """ask_human — DEPRECATED. Use ask_user instead.

    Behaviour-compatible thin shim: emits the same chat.question event
    shape (without options) and returns the user's text answer.
    """

    name = "ask_human"
    description = (
        "(deprecated, use ask_user) "
        "Ask the user a free-form question and wait for their response. "
        "The user's text response is returned to you."
    )

    def __init__(self, event_bus: Any | None = None):
        self.event_bus = event_bus

    def create(self) -> PydanticAITool:
        bus = self.event_bus

        async def ask_human(ctx: RunContext, question: str) -> str:
            question_id = str(uuid.uuid4())
            future = await _human_io.register(question_id)

            if bus:
                bus.emit("chat.question", {
                    "node_id": ctx.deps.agent_name,
                    "agent_name": ctx.deps.agent_name,
                    "question_id": question_id,
                    "question": question,
                    "header": None,
                    "options": None,
                    "multi_select": False,
                    "allow_custom_input": True,
                    "input_type": "textarea",
                    "input_placeholder": None,
                })

            raw = await _human_io.wait(future, timeout=DEFAULT_TIMEOUT_SEC)
            if raw is None:
                return TIMEOUT_MESSAGE
            payload = raw if isinstance(raw, dict) else {"answer": str(raw)}
            return assemble_answer(payload, None, False, True)

        return PydanticAITool(
            ask_human,
            takes_ctx=True,
            description=self.description,
        )
