"""Regression tests for the StdinCoordinator ↔ ask_user wiring.

These lock the incremental-guarantee contract: registering a coordinator
must route ask_user through stdin; NOT registering one must leave every
existing path (WS Future, plain stdin fallback) byte-for-byte unchanged.

Any future change to ask_user.py that breaks these tests is a regression
of the "CLI mode is opt-in" invariant.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harness.extensions.tui import (
    StdinCoordinator,
    get_stdin_coordinator,
    set_stdin_coordinator,
)
from harness.tools import _human_io, ask_user as ask_user_mod


@pytest.fixture(autouse=True)
def _reset_coordinator():
    """Clear the singleton before and after every test.

    Tests run in a single process; a stale coordinator registered by an
    earlier test would silently route every later ask_user call through
    stdin and corrupt assertions.
    """
    set_stdin_coordinator(None)
    yield
    set_stdin_coordinator(None)


@pytest.fixture(autouse=True)
def _clear_pending_futures():
    """Drop any futures left in the process-wide pending registry."""
    _human_io._pending.clear()
    yield
    _human_io._pending.clear()


class _Deps:
    agent_name = "test-agent"
    workflow_id = "wf-test"


class _Ctx:
    def __init__(self):
        self.deps = _Deps()


# ---------------------------------------------------------------------------
# Singleton behavior
# ---------------------------------------------------------------------------


def test_get_stdin_coordinator_returns_none_by_default():
    """No coordinator registered → ask_user falls through to existing paths."""
    assert get_stdin_coordinator() is None


def test_set_stdin_coordinator_round_trip():
    coord = StdinCoordinator()
    set_stdin_coordinator(coord)
    assert get_stdin_coordinator() is coord


def test_set_stdin_coordinator_none_clears():
    set_stdin_coordinator(StdinCoordinator())
    set_stdin_coordinator(None)
    assert get_stdin_coordinator() is None


# ---------------------------------------------------------------------------
# ask_user routing — the core incremental-guarantee regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_user_routes_to_stdin_when_coordinator_set():
    """When a coordinator is registered, ask_user must take the stdin path:
    call ``_read_answer_from_stdin`` and NOT touch ``_human_io.register``
    or ``bus.emit('chat.question', ...)``.

    This is the CLI TUI case: a Bus is injected (for hook event delivery
    to TuiRenderer / default plugins) but no WS subscriber will ever
    resolve the Future, so the WS path would deadlock. The coordinator
    redirects to stdin instead.
    """
    bus = MagicMock()
    bus.emit = MagicMock()
    factory = ask_user_mod.AskUserToolFactory(event_bus=bus)
    tool = factory.create()

    set_stdin_coordinator(StdinCoordinator())

    async def fake_read(question, header, options):
        # Confirm the call signature matches the existing fallback. Returns
        # the resolved label (what the real _read_answer_from_stdin yields
        # after _parse_stdin_indices translates "1" → "A").
        assert question == "Pick one"
        assert header == "Choice"
        assert options is not None
        return "A"

    with (
        patch.object(
            ask_user_mod, "_read_answer_from_stdin", new=AsyncMock(side_effect=fake_read)
        ) as mock_read,
        patch.object(_human_io, "register", new=AsyncMock()) as mock_register,
    ):
        result = await tool.function(
            _Ctx(),
            question="Pick one",
            options=[ask_user_mod.AskUserOption(label="A", value="a")],
            header="Choice",
        )

    assert result == "A"
    mock_read.assert_awaited_once()
    mock_register.assert_not_awaited()
    # The bus is present but the WS path is bypassed — no chat.question emitted.
    bus.emit.assert_not_called()


@pytest.mark.asyncio
async def test_ask_user_falls_through_to_ws_when_coordinator_unset():
    """No coordinator registered → existing WS path is unchanged:
    ``_human_io.register`` is called and ``chat.question`` is emitted on the
    bus, exactly as before this feature landed.
    """
    bus = MagicMock()
    bus.emit = MagicMock()
    factory = ask_user_mod.AskUserToolFactory(event_bus=bus)
    tool = factory.create()

    # No set_stdin_coordinator(...) — left at None by the fixture.

    async def resolve_after_register():
        # Wait for register() to be called, then deliver an answer.
        for _ in range(100):
            if _human_io._pending:
                break
            await asyncio.sleep(0.005)
        qid = next(iter(_human_io._pending.keys()))
        await _human_io.resolve(qid, {"selected": ["a"], "custom_input": ""})

    with (
        patch.object(
            ask_user_mod, "_read_answer_from_stdin", new=AsyncMock()
        ) as mock_read_stdin,
        patch.object(_human_io, "register", new=AsyncMock(wraps=_human_io.register)) as mock_register,
    ):
        coro = tool.function(
            _Ctx(),
            question="Pick",
            options=[ask_user_mod.AskUserOption(label="A", value="a")],
        )
        result, _ = await asyncio.gather(coro, resolve_after_register())

    assert result == "A"
    mock_register.assert_awaited()
    mock_read_stdin.assert_not_awaited()
    # chat.question MUST be emitted — this is the WS path's defining side effect.
    emitted_types = [call.args[0] for call in bus.emit.call_args_list]
    assert "chat.question" in emitted_types


@pytest.mark.asyncio
async def test_ask_user_routes_to_stdin_when_bus_is_none_and_no_coordinator():
    """Pre-existing bus=None path (plain Python script, no Bus injected) must
    still work: falls back to ``_read_answer_from_stdin``. Coordinator
    absent, so no pause/resume happens, but the input path is exercised.
    """
    factory = ask_user_mod.AskUserToolFactory(event_bus=None)
    tool = factory.create()

    with patch.object(
        ask_user_mod, "_read_answer_from_stdin", new=AsyncMock(return_value="free text")
    ) as mock_read:
        result = await tool.function(_Ctx(), question="Open ended?")

    assert result == "free text"
    mock_read.assert_awaited_once()


# ---------------------------------------------------------------------------
# _input_blocking coordination — pause/resume around input()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_input_blocking_pauses_and_resumes_coordinator():
    """When a coordinator is registered, ``_input_blocking`` must call
    ``pause`` before the threaded input and ``resume`` after. Locking this
    protects the Live renderer from being stomped by an interleaving refresh.
    """
    coord = StdinCoordinator()
    coord.pause = MagicMock()
    coord.resume = MagicMock()
    set_stdin_coordinator(coord)

    with patch.object(ask_user_mod, "_sync_input", return_value="answer") as mock_sync:
        result = await ask_user_mod._input_blocking("prompt> ")

    assert result == "answer"
    mock_sync.assert_called_once_with("prompt> ")
    coord.pause.assert_called_once()
    coord.resume.assert_called_once()


@pytest.mark.asyncio
async def test_input_blocking_skips_pause_when_no_coordinator():
    """Without a coordinator, ``_input_blocking`` is the legacy behavior —
    no pause/resume calls, plain threaded input.
    """
    with patch.object(ask_user_mod, "_sync_input", return_value="answer") as mock_sync:
        result = await ask_user_mod._input_blocking("prompt> ")

    assert result == "answer"
    mock_sync.assert_called_once_with("prompt> ")


@pytest.mark.asyncio
async def test_input_blocking_resumes_even_on_exception():
    """If the threaded input raises, ``resume`` must still fire so the
    Live renderer is not left stopped.
    """
    coord = StdinCoordinator()
    coord.pause = MagicMock()
    coord.resume = MagicMock()
    set_stdin_coordinator(coord)

    with patch.object(ask_user_mod, "_sync_input", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            await ask_user_mod._input_blocking("prompt> ")

    coord.pause.assert_called_once()
    coord.resume.assert_called_once()
