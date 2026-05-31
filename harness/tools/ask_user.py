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
             | { "answer": "..." }                          (legacy format)
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
        "Ask the user a question and wait for their response. "
        "SUPPORTS THREE MODES — pick the one that fits:\n"
        "1. Multiple-choice: set options=[{label, description?, value?}, ...]. "
        "Use multi_select=True for checkbox (pick several). Default multi_select=False for radio (pick one).\n"
        "2. Open-ended: omit options. The user types a free-form answer. "
        "Set input_type='textarea' for long answers, 'number' for numeric, 'url' for URLs.\n"
        "3. Choice + other: set options AND allow_custom_input=True (default). "
        "The user can pick options AND type extra text.\n\n"
        "ALWAYS set header (short label like 'Model' or 'Priority') when using options. "
        "ALWAYS provide 2-6 options with concise labels (<=30 chars). "
        "Add description per option when the label alone is ambiguous.\n\n"
        "Returns the user's answer as a plain string. "
        "Blocks until answered or 5 min timeout."
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
            """Ask the user a question and wait for their answer.

            Modes:
              - Multiple-choice: pass options list. single-select (default) or multi_select=True.
              - Open-ended: omit options. user types free text. Use input_type for keyboard hints.
              - Choice + other: options + allow_custom_input=True (default).

            Args:
                question: The question to ask. Be specific.
                options: Choice list. Each item: {label (button text), description? (tooltip), value? (return value, defaults to label)}.
                         2-6 items recommended. Omit for open-ended questions.
                header: Short label shown above the question (e.g. 'Model', 'Priority'). Max 12 chars.
                multi_select: True = user can pick multiple options (checkboxes). False = single pick (radio). Default False.
                allow_custom_input: True = show an 'Other' text box alongside options. Default True.
                                    Set False to force a choice from the list only.
                input_type: Keyboard hint for the free-text input: 'text', 'number', 'url', or 'textarea'. Default 'text'.
                input_placeholder: Placeholder text in the free-text input box (e.g. 'Or type a model name...').

            Returns:
                The user's answer as a plain string.
                Single choice: "Sonnet 4.6"
                Multi choice: "Sonnet 4.6, Opus 4.7"
                Free text only: whatever the user typed
                Choice + other: "Sonnet 4.6 | other: also consider Gemini"
            """
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
