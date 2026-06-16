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

    def emit(self, type_: str, payload: dict, **kwargs):
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


# ---------- chat.answer / chat.timeout emission (P0 refresh fix) ----------

@pytest.mark.asyncio
async def test_emits_chat_answer_on_resolve():
    """When the user resolves a question, chat.answer must be emitted so
    late WS subscribers (page refresh, new tab) see the resolved state
    via replay instead of re-prompting."""
    bus = _StubBus()
    factory = AskUserToolFactory(event_bus=bus)
    tool = factory.create()

    async def answer_later():
        for _ in range(50):
            if bus.events:
                break
            await asyncio.sleep(0.005)
        qid = bus.events[0][1]["question_id"]
        await resolve_answer(qid, {"selected": ["a"], "custom_input": ""})

    coro = tool.function(
        _Ctx(),
        question="Pick",
        options=[AskUserOption(label="A", value="a")],
    )
    result, _ = await asyncio.gather(coro, answer_later())

    assert result == "A"
    # chat.question first, chat.answer second
    event_types = [e[0] for e in bus.events]
    assert "chat.question" in event_types
    assert "chat.answer" in event_types
    assert event_types.index("chat.answer") > event_types.index("chat.question")

    answer_payload = next(p for t, p in bus.events if t == "chat.answer")
    assert answer_payload["answer"] == "A"
    assert answer_payload["question_id"] == bus.events[0][1]["question_id"]
    # raw is included for clients that need the structured form
    assert answer_payload["raw"] == {"selected": ["a"], "custom_input": ""}


@pytest.mark.asyncio
async def test_emits_chat_timeout_on_timeout(monkeypatch):
    """When the future times out, chat.timeout must be emitted so the UI
    can render the timed-out state instead of leaving the prompt open."""
    bus = _StubBus()
    factory = AskUserToolFactory(event_bus=bus)
    tool = factory.create()

    async def instant_timeout(future, timeout):
        return None

    monkeypatch.setattr(_human_io, "wait", instant_timeout)

    result = await tool.function(_Ctx(), question="Q")
    assert result == TIMEOUT_MESSAGE

    event_types = [e[0] for e in bus.events]
    assert "chat.timeout" in event_types
    timeout_payload = next(p for t, p in bus.events if t == "chat.timeout")
    assert timeout_payload["question_id"] == bus.events[0][1]["question_id"]


# ---------- HARNESS_ASK_USER_TIMEOUT env config ----------

def test_resolve_timeout_default_is_none():
    """Default (env unset) = wait forever (None)."""
    import os
    monkeypatch_env = {"HARNESS_ASK_USER_TIMEOUT": ""}
    old = os.environ.pop("HARNESS_ASK_USER_TIMEOUT", None)
    try:
        if "HARNESS_ASK_USER_TIMEOUT" not in os.environ:
            from harness.tools.ask_user import _resolve_timeout
            assert _resolve_timeout() is None
    finally:
        if old is not None:
            os.environ["HARNESS_ASK_USER_TIMEOUT"] = old


def test_resolve_timeout_explicit_wait_forever(monkeypatch):
    monkeypatch.setenv("HARNESS_ASK_USER_TIMEOUT", "-1")
    from harness.tools.ask_user import _resolve_timeout
    assert _resolve_timeout() is None


def test_resolve_timeout_explicit_seconds(monkeypatch):
    monkeypatch.setenv("HARNESS_ASK_USER_TIMEOUT", "120")
    from harness.tools.ask_user import _resolve_timeout
    assert _resolve_timeout() == 120.0


def test_resolve_timeout_rejects_zero(monkeypatch):
    monkeypatch.setenv("HARNESS_ASK_USER_TIMEOUT", "0")
    from harness.tools.ask_user import _resolve_timeout
    with pytest.raises(RuntimeError, match="invalid"):
        _resolve_timeout()


def test_resolve_timeout_accepts_float_seconds(monkeypatch):
    """Float seconds (e.g. 1.5) must be accepted, not rejected as 'not an integer'."""
    monkeypatch.setenv("HARNESS_ASK_USER_TIMEOUT", "1.5")
    from harness.tools.ask_user import _resolve_timeout
    assert _resolve_timeout() == 1.5


def test_resolve_timeout_rejects_garbage(monkeypatch):
    monkeypatch.setenv("HARNESS_ASK_USER_TIMEOUT", "soon")
    from harness.tools.ask_user import _resolve_timeout
    with pytest.raises(RuntimeError, match="not a number"):
        _resolve_timeout()


# ---------- CLI / stdin fallback ----------

@pytest.mark.asyncio
async def test_stdin_fallback_when_no_bus(monkeypatch):
    """When no bus is wired (CLI mode), ask_user must read from stdin
    instead of registering a future that will never resolve."""
    factory = AskUserToolFactory(event_bus=None)
    tool = factory.create()

    async def fake_input(prompt: str) -> str:
        return "1"

    monkeypatch.setattr(
        "harness.tools.ask_user._input_blocking",
        fake_input,
    )

    result = await tool.function(
        _Ctx(),
        question="Pick one",
        header="Model",
        options=[
            AskUserOption(label="Sonnet", value="sonnet"),
            AskUserOption(label="Opus", value="opus"),
        ],
    )
    assert result == "Sonnet"


@pytest.mark.asyncio
async def test_stdin_fallback_open_ended(monkeypatch):
    factory = AskUserToolFactory(event_bus=None)
    tool = factory.create()

    async def fake_input(prompt: str) -> str:
        return "free text answer"

    monkeypatch.setattr(
        "harness.tools.ask_user._input_blocking",
        fake_input,
    )

    result = await tool.function(_Ctx(), question="What's your name?")
    assert result == "free text answer"


@pytest.mark.asyncio
async def test_stdin_fallback_falls_back_to_raw_text(monkeypatch):
    """If user types text that isn't an index, fall back to raw input."""
    factory = AskUserToolFactory(event_bus=None)
    tool = factory.create()

    async def fake_input(prompt: str) -> str:
        return "  custom model name  "

    monkeypatch.setattr(
        "harness.tools.ask_user._input_blocking",
        fake_input,
    )

    result = await tool.function(
        _Ctx(),
        question="Pick",
        options=[AskUserOption(label="A"), AskUserOption(label="B")],
    )
    assert result == "custom model name"


@pytest.mark.asyncio
async def test_stdin_eof_raises_loud(monkeypatch):
    """EOF on stdin (no interactive terminal) must raise, not silently
    return empty. Returning empty would let the agent proceed on a blank
    answer with no signal — explicit failure is the contract."""
    factory = AskUserToolFactory(event_bus=None)
    tool = factory.create()

    # Patch builtins.input (not _sync_input) so the real try/except path
    # runs and we verify the EOFError → RuntimeError wrapping.
    import builtins
    monkeypatch.setattr(builtins, "input", lambda *a, **kw: (_ for _ in ()).throw(EOFError()))

    with pytest.raises(RuntimeError, match="EOF"):
        await tool.function(_Ctx(), question="Q")


@pytest.mark.asyncio
async def test_stdin_concurrent_calls_serialize_via_lock(monkeypatch):
    """Two concurrent ask_user stdin calls must NOT interleave — the
    process-wide asyncio.Lock enforces one-at-a-time prompting. Verified
    by recording the prompt windows and asserting no overlap."""
    factory = AskUserToolFactory(event_bus=None)
    tool = factory.create()

    windows: list[tuple[str, float, float]] = []
    counter = {"n": 0}

    def fake_sync_input(prompt: str) -> str:
        import time
        counter["n"] += 1
        my_id = counter["n"]
        start = time.monotonic()
        # Hold the "input" for 50ms so a non-serialized sibling would overlap.
        time.sleep(0.05)
        end = time.monotonic()
        windows.append((f"call-{my_id}", start, end))
        return "yes"

    # Patch the leaf so the real _input_blocking (lock + to_thread) runs.
    monkeypatch.setattr(
        "harness.tools.ask_user._sync_input",
        fake_sync_input,
    )

    await asyncio.gather(
        tool.function(_Ctx(), question="Q1"),
        tool.function(_Ctx(), question="Q2"),
    )

    assert len(windows) == 2
    # Sort by start time; assert no overlap.
    windows.sort(key=lambda w: w[1])
    _, _, earlier_end = windows[0]
    _, later_start, _ = windows[1]
    assert later_start >= earlier_end, (
        f"stdin calls overlapped: window 0 ended at {earlier_end:.4f}, "
        f"window 1 started at {later_start:.4f}"
    )
