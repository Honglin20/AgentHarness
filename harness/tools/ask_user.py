"""ask_user tool — structured human-in-the-loop questions.

Supports single-/multi-choice options, free-form text, or both combined.
Returns a single string assembled from the user's structured answer.
"""

from __future__ import annotations

import asyncio
import os
import sys
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


# Timeout is configurable via env. Default -1 = wait forever (human-in-the-loop
# should not silently auto-skip). Positive int = N seconds. 0 is invalid.
#
# History: hard-coded 60s caused two real defects:
#   (1) Refresh during a question → future lost → 60s later agent got
#       TIMEOUT_MESSAGE and proceeded with wrong context.
#   (2) `python run_workflow(ui=False)` had no WS subscriber → 60s timeout
#       was the only possible outcome, HITL was effectively unusable.
def _resolve_timeout() -> float | None:
    raw = os.environ.get("HARNESS_ASK_USER_TIMEOUT", "-1")
    try:
        n = float(raw)
    except ValueError:
        raise RuntimeError(
            f"HARNESS_ASK_USER_TIMEOUT={raw!r} is not a number. "
            "Use -1 (wait forever) or a positive number of seconds (e.g. 60 or 1.5)."
        )
    if n == -1:
        return None
    if n <= 0:
        raise RuntimeError(
            f"HARNESS_ASK_USER_TIMEOUT={n} is invalid. Use -1 (wait forever) or >= 1 second."
        )
    return n


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
        "FORMATTING: The question text is rendered as Markdown. "
        "Use markdown tables for comparisons, bullet lists for multiple items, "
        "and headers to separate sections. NEVER dump a long unformatted paragraph — "
        "structure the question so it's easy to scan at a glance.\n\n"
        "Returns the user's answer as a plain string. "
        "Blocks until answered (default waits forever; configurable via "
        "HARNESS_ASK_USER_TIMEOUT env)."
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
            timeout = _resolve_timeout()
            wid = getattr(ctx.deps, "workflow_id", None)

            # CLI TUI mode: a StdinCoordinator is registered only by
            # `harness run` when a TTY is attached. Route through stdin
            # (with Live pause/resume coordinated via _input_blocking) even
            # though a Bus may be present — the Bus is injected for hook
            # event delivery to TuiRenderer / default plugins, but no WS
            # subscriber will ever resolve a chat.question Future in CLI
            # mode, so the WS path would deadlock.
            #
            # Unregistered → falls through to the bus / stdin branches
            # below, byte-for-byte preserving server / run_*.py / plain
            # Python paths. This invariant is locked by
            # tests/extensions/tui/test_ask_user_coordinator.py.
            from harness.extensions.tui.coordinator import get_stdin_coordinator

            if get_stdin_coordinator() is not None:
                raw = await _read_answer_from_stdin(question, header, options)
                payload = _normalize_raw(raw)
                return assemble_answer(payload, options, multi_select, allow_custom_input)

            # No bus → CLI / script mode. Fall back to stdin so HITL works
            # outside the server. With a bus, emit and wait for the WS path
            # even if there are zero subscribers — a browser may connect later
            # (e.g. user just hasn't opened the page yet).
            if bus is None:
                raw = await _read_answer_from_stdin(question, header, options)
                payload = _normalize_raw(raw)
                return assemble_answer(payload, options, multi_select, allow_custom_input)

            future = await _human_io.register(question_id)

            question_payload: dict[str, Any] = {
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
            }
            if wid:
                question_payload["workflow_id"] = wid
            bus.emit("chat.question", question_payload)

            raw = await _human_io.wait(future, timeout=timeout)
            if raw is None:
                bus.emit("chat.timeout", {
                    "workflow_id": wid,
                    "node_id": ctx.deps.agent_name,
                    "agent_name": ctx.deps.agent_name,
                    "question_id": question_id,
                    "timeout_sec": timeout,
                })
                return TIMEOUT_MESSAGE

            payload = _normalize_raw(raw)
            answer_str = assemble_answer(payload, options, multi_select, allow_custom_input)
            # Emit chat.answer so late subscribers (page refresh, new tab)
            # see the resolved state via WS replay instead of re-prompting.
            bus.emit("chat.answer", {
                "workflow_id": wid,
                "node_id": ctx.deps.agent_name,
                "agent_name": ctx.deps.agent_name,
                "question_id": question_id,
                "answer": answer_str,
                "raw": payload,
            })
            return answer_str

        return PydanticAITool(
            self._wrap_fn(ask_user, self.name),
            takes_ctx=True,
            description=self.description,
        )


async def resolve_answer(question_id: str, payload: dict[str, Any] | str) -> bool:
    """Public entry for WS handler to deliver a user's structured answer."""
    return await _human_io.resolve(question_id, payload)


def _normalize_raw(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"answer": raw}
    if isinstance(raw, dict):
        return raw
    return {"answer": str(raw)}


async def _read_answer_from_stdin(
    question: str,
    header: str | None,
    options: list[AskUserOption] | None,
) -> str:
    """CLI fallback when no Bus is wired (e.g. `python run_workflow(ui=False)`).

    Blocks on stdin via a thread so the event loop isn't frozen. Serializes
    concurrent calls via a process-wide lock — without it, two parallel
    ask_user prompts would interleave on stdin and produce undefined input
    routing. Workflows that need true parallel HITL must use the UI.

    Does NOT emit chat.question / chat.answer events — there is no bus to
    emit through. If a workflow wires a bus after the fact (dynamic
    extension registration), WS subscribers will not see this exchange.
    """
    lines = []
    if header:
        lines.append(f"[{header}]")
    lines.append(question)
    if options:
        for i, opt in enumerate(options, 1):
            label = opt.label
            desc = f" — {opt.description}" if opt.description else ""
            lines.append(f"  {i}. {label}{desc}")
        lines.append("Enter comma-separated indices (or type your own answer):")
    else:
        lines.append("Answer:")
    prompt = "\n".join(lines) + "\n> "

    raw = await _input_blocking(prompt)

    if options:
        selected = _parse_stdin_indices(raw, options)
        if selected is not None:
            return ",".join(selected) if selected else raw.strip()
    return raw.strip()


_stdin_lock: asyncio.Lock | None = None


def _get_stdin_lock() -> asyncio.Lock:
    global _stdin_lock
    if _stdin_lock is None:
        _stdin_lock = asyncio.Lock()
    return _stdin_lock


async def _input_blocking(prompt: str) -> str:
    """Run input() in a worker thread so the asyncio loop stays responsive.

    Serialized via a process-wide asyncio.Lock — two concurrent stdin
    fallbacks would otherwise interleave their prompts on the terminal
    and the user's typed answer could route to whichever input() call
    finished first. The lock enforces one-at-a-time prompting. If the
    workflow actually has parallel human-in-the-loop needs, the user
    must run with `ui=True` and use the browser.

    When a StdinCoordinator is registered (`harness run` TUI mode), Live
    is paused before the threaded input and resumed after — preventing
    the Live refresh loop from stomping the input prompt. Without a
    coordinator this is the legacy path.
    """
    from harness.extensions.tui.coordinator import get_stdin_coordinator

    coord = get_stdin_coordinator()
    if coord is not None:
        coord.pause()
    try:
        lock = _get_stdin_lock()
        async with lock:
            return await asyncio.to_thread(_sync_input, prompt)
    finally:
        if coord is not None:
            coord.resume()


def _sync_input(prompt: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    try:
        return input()
    except EOFError as e:
        # No stdin connected (piped script, containerized run, daemon mode).
        # Raise — ask_user is human-in-the-loop and silently returning empty
        # would let the agent proceed on an empty answer with no signal.
        # Callers catching at workflow boundary can surface this as a
        # workflow-level failure.
        raise RuntimeError(
            "ask_user stdin fallback got EOF — no interactive stdin available. "
            "Either run with `ui=True` (opens browser) or pipe an answer into stdin."
        ) from e


def _parse_stdin_indices(raw: str, options: list[AskUserOption]) -> list[str] | None:
    """Parse '1,3' style input into option labels. Returns None if input
    doesn't look like an index list (so caller falls back to raw text)."""
    text = raw.strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return None
    indices: list[int] = []
    for p in parts:
        if not p.isdigit():
            return None
        idx = int(p)
        if idx < 1 or idx > len(options):
            return None
        indices.append(idx)
    return [options[i - 1].label for i in indices]
