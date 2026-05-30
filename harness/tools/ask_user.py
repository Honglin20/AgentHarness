"""ask_user tool — structured human-in-the-loop questions.

Supports single-/multi-choice options, free-form text, or both combined.
Returns a single string assembled from the user's structured answer.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools import _human_io
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory


class AskUserOption(BaseModel):
    label: str = Field(..., description="Short button text (<=30 chars)")
    description: str | None = Field(None, description="Tooltip / sub-text (<=120 chars)")
    value: str | None = Field(None, description="String returned to the LLM; defaults to label")


DEFAULT_TIMEOUT_SEC = 300.0
TIMEOUT_MESSAGE = "User disconnected. Proceed with your best judgment."


def assemble_answer(
    payload: dict[str, Any],
    options: list[AskUserOption] | None,
    multi_select: bool,
    allow_custom_input: bool,
) -> str:
    """Compose the string returned to the LLM from a structured answer payload.

    payload = { "selected": [...], "custom_input": "..." }  (new)
             | { "answer": "..." }                          (legacy ask_human)
    """
    if "answer" in payload and "selected" not in payload and "custom_input" not in payload:
        return str(payload.get("answer") or "")

    selected_raw = payload.get("selected") or []
    if not isinstance(selected_raw, list):
        selected_raw = []
    custom_input = str(payload.get("custom_input") or "").strip()

    valid_values: set[str] = set()
    value_to_label: dict[str, str] = {}
    if options:
        for opt in options:
            v = opt.value if opt.value is not None else opt.label
            valid_values.add(v)
            value_to_label[v] = opt.label

    seen: set[str] = set()
    selected: list[str] = []
    for v in selected_raw:
        if not isinstance(v, str):
            continue
        if options and v not in valid_values:
            continue
        if v in seen:
            continue
        seen.add(v)
        selected.append(v)

    if not multi_select and len(selected) > 1:
        selected = selected[:1]

    if not allow_custom_input:
        custom_input = ""

    labels = [value_to_label.get(v, v) for v in selected]
    sel_part = ", ".join(labels)

    if sel_part and custom_input:
        return f"{sel_part} | other: {custom_input}"
    if sel_part:
        return sel_part
    return custom_input


class AskUserToolFactory(ToolFactory):
    """ask_user — structured question tool with options + free-input."""

    name = "ask_user"
    description = (
        "Ask the user a structured question. "
        "Provide `options` for multiple-choice prompts (set `multi_select=true` for checkbox-style). "
        "Set `allow_custom_input=true` to additionally accept free-form text alongside options. "
        "Omit `options` to ask an open-ended question. "
        "Blocks until the user submits and returns their answer as a plain string."
    )

    def __init__(self, event_bus: Any | None = None):
        self.event_bus = event_bus

    def create(self) -> PydanticAITool:
        bus = self.event_bus

        async def ask_user(
            ctx: RunContext,
            question: str,
            options: list[AskUserOption] | None = None,
            header: str | None = None,
            multi_select: bool = False,
            allow_custom_input: bool = True,
            input_type: Literal["text", "number", "url", "textarea"] = "text",
            input_placeholder: str | None = None,
        ) -> str:
            question_id = str(uuid.uuid4())
            future = await _human_io.register(question_id)

            if bus:
                bus.emit("chat.question", {
                    "node_id": ctx.deps.agent_name,
                    "agent_name": ctx.deps.agent_name,
                    "question_id": question_id,
                    "question": question,
                    "header": header,
                    "options": [o.model_dump() for o in options] if options else None,
                    "multi_select": multi_select,
                    "allow_custom_input": allow_custom_input,
                    "input_type": input_type,
                    "input_placeholder": input_placeholder,
                })

            raw = await _human_io.wait(future, timeout=DEFAULT_TIMEOUT_SEC)
            if raw is None:
                return TIMEOUT_MESSAGE
            if isinstance(raw, str):
                payload = {"answer": raw}
            elif isinstance(raw, dict):
                payload = raw
            else:
                payload = {"answer": str(raw)}
            return assemble_answer(payload, options, multi_select, allow_custom_input)

        return PydanticAITool(
            ask_user,
            takes_ctx=True,
            description=self.description,
        )


async def resolve_answer(question_id: str, payload: dict[str, Any] | str) -> bool:
    """Public entry for WS handler to deliver a user's structured answer."""
    return await _human_io.resolve(question_id, payload)
