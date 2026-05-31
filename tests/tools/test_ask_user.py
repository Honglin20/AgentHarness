"""Tests for ask_user tool."""

from __future__ import annotations

import asyncio

import pytest
from pydantic_ai import Tool as PydanticAITool

from harness.tools import _human_io
from harness.tools.ask_user import (
    AskUserOption,
    AskUserToolFactory,
    TIMEOUT_MESSAGE,
    assemble_answer,
    resolve_answer,
)


# ---------- assemble_answer pure-logic tests ----------

def _opts(*pairs: tuple[str, str]) -> list[AskUserOption]:
    return [AskUserOption(label=lbl, value=val) for lbl, val in pairs]


def test_assemble_legacy_answer():
    out = assemble_answer({"answer": "hello"}, None, False, True)
    assert out == "hello"


def test_assemble_pure_text():
    out = assemble_answer(
        {"selected": [], "custom_input": "free text"},
        None, False, True,
    )
    assert out == "free text"


def test_assemble_single_select_value_to_label():
    opts = _opts(("Sonnet 4.6", "claude-sonnet-4-6"))
    out = assemble_answer(
        {"selected": ["claude-sonnet-4-6"], "custom_input": ""},
        opts, False, True,
    )
    assert out == "Sonnet 4.6"


def test_assemble_multi_select_joined():
    opts = _opts(("A", "a"), ("B", "b"), ("C", "c"))
    out = assemble_answer(
        {"selected": ["a", "c"], "custom_input": ""},
        opts, True, True,
    )
    assert out == "A, C"


def test_assemble_single_select_truncates_extras():
    opts = _opts(("A", "a"), ("B", "b"))
    out = assemble_answer(
        {"selected": ["a", "b"], "custom_input": ""},
        opts, False, True,
    )
    assert out == "A"


def test_assemble_drops_invalid_values():
    opts = _opts(("A", "a"), ("B", "b"))
    out = assemble_answer(
        {"selected": ["a", "bogus"], "custom_input": ""},
        opts, True, True,
    )
    assert out == "A"


def test_assemble_dedupes_selected():
    opts = _opts(("A", "a"), ("B", "b"))
    out = assemble_answer(
        {"selected": ["a", "a", "b"], "custom_input": ""},
        opts, True, True,
    )
    assert out == "A, B"


def test_assemble_options_plus_other():
    opts = _opts(("A", "a"))
    out = assemble_answer(
        {"selected": ["a"], "custom_input": "also Gemini"},
        opts, True, True,
    )
    assert out == "A | other: also Gemini"


def test_assemble_disallowed_custom_input_dropped():
    opts = _opts(("A", "a"))
    out = assemble_answer(
        {"selected": ["a"], "custom_input": "ignored"},
        opts, False, False,
    )
    assert out == "A"


def test_assemble_option_without_value_falls_back_to_label():
    opts = [AskUserOption(label="Yes"), AskUserOption(label="No")]
    out = assemble_answer(
        {"selected": ["Yes"], "custom_input": ""},
        opts, False, True,
    )
    assert out == "Yes"


# ---------- factory contract ----------

def test_factory_name_and_description():
    f = AskUserToolFactory(event_bus=None)
    assert f.name == "ask_user"
    assert "ask the user" in f.description.lower()


def test_factory_creates_pydantic_ai_tool():
    f = AskUserToolFactory(event_bus=None)
    tool = f.create()
    assert isinstance(tool, PydanticAITool)
    assert tool.name == "ask_user"
    assert tool.takes_ctx is True


# ---------- resolve_answer wiring ----------

@pytest.mark.asyncio
async def test_resolve_answer_returns_false_when_no_pending():
    found = await resolve_answer("nonexistent-qid", {"selected": [], "custom_input": ""})
    assert found is False


@pytest.mark.asyncio
async def test_resolve_answer_completes_future():
    qid = "qid-resolve-test"
    fut = await _human_io.register(qid)
    found = await resolve_answer(qid, {"selected": ["x"], "custom_input": ""})
    assert found is True
    assert fut.done()
    assert fut.result() == {"selected": ["x"], "custom_input": ""}


# ---------- end-to-end tool body (via EventBus stub) ----------

class _StubBus:
    def __init__(self):
        self.events = []

    def emit(self, type_: str, payload: dict):
        self.events.append((type_, payload))


class _Deps:
    agent_name = "test-agent"


class _Ctx:
    def __init__(self):
        self.deps = _Deps()


@pytest.mark.asyncio
async def test_tool_emits_event_and_returns_assembled_answer():
    bus = _StubBus()
    factory = AskUserToolFactory(event_bus=bus)
    tool = factory.create()

    options = [
        AskUserOption(label="A", value="a"),
        AskUserOption(label="B", value="b"),
    ]

    async def answer_later():
        # Wait for the event to be emitted, then resolve it.
        for _ in range(50):
            if bus.events:
                break
            await asyncio.sleep(0.005)
        qid = bus.events[0][1]["question_id"]
        await resolve_answer(qid, {"selected": ["a", "b"], "custom_input": "extra"})

    coro = tool.function(
        _Ctx(),
        question="Pick",
        options=options,
        header="Pick",
        multi_select=True,
        allow_custom_input=True,
        input_type="text",
        input_placeholder=None,
    )
    result, _ = await asyncio.gather(coro, answer_later())

    assert result == "A, B | other: extra"
    assert bus.events[0][0] == "chat.question"
    payload = bus.events[0][1]
    assert payload["multi_select"] is True
    assert payload["allow_custom_input"] is True
    assert payload["options"][0]["value"] == "a"


@pytest.mark.asyncio
async def test_tool_timeout_returns_disconnect_string(monkeypatch):
    bus = _StubBus()
    factory = AskUserToolFactory(event_bus=bus)
    tool = factory.create()

    # Patch wait to immediately time out (returns None).
    async def instant_timeout(future, timeout):
        return None

    monkeypatch.setattr(_human_io, "wait", instant_timeout)

    result = await tool.function(
        _Ctx(),
        question="Q",
        options=None,
        header=None,
        multi_select=False,
        allow_custom_input=True,
        input_type="text",
        input_placeholder=None,
    )
    assert result == TIMEOUT_MESSAGE


@pytest.mark.asyncio
async def test_tool_accepts_legacy_string_answer():
    """When WS handler resolves with a raw string (legacy chat.answer.answer),
    the tool should still return a clean string."""
    bus = _StubBus()
    factory = AskUserToolFactory(event_bus=bus)
    tool = factory.create()

    async def answer_later():
        for _ in range(50):
            if bus.events:
                break
            await asyncio.sleep(0.005)
        qid = bus.events[0][1]["question_id"]
        # Resolve directly with a raw string (legacy path).
        await _human_io.resolve(qid, "plain text")

    coro = tool.function(
        _Ctx(),
        question="open-ended",
        options=None,
        header=None,
        multi_select=False,
        allow_custom_input=True,
        input_type="textarea",
        input_placeholder=None,
    )
    result, _ = await asyncio.gather(coro, answer_later())
    assert result == "plain text"


# ---------- ask_user open-ended mode (legacy ask_human behavior) ----------

@pytest.mark.asyncio
async def test_ask_user_open_ended_round_trip():
    from harness.tools.ask_user import AskUserToolFactory, resolve_answer

    bus = _StubBus()
    factory = AskUserToolFactory(event_bus=bus)
    tool = factory.create()

    async def answer_later():
        for _ in range(50):
            if bus.events:
                break
            await asyncio.sleep(0.005)
        qid = bus.events[0][1]["question_id"]
        await resolve_answer(qid, {"answer": "user said hi"})

    coro = tool.function(_Ctx(), question="Hello?")
    result, _ = await asyncio.gather(coro, answer_later())
    assert result == "user said hi"
    # Open-ended mode should have options=None
    payload = bus.events[0][1]
    assert payload["options"] is None
