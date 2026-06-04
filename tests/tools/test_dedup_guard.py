"""Tests for ToolDedupGuard — tool call deduplication within a time window."""

import asyncio
import time

import pytest

from harness.tools.dedup_guard import ToolDedupGuard, configure_dedup, get_dedup_guard


@pytest.fixture(autouse=True)
def _reset_guard():
    """Reset module-level dedup guard before and after each test."""
    import harness.tools.dedup_guard as mod
    mod._guard = None
    yield
    mod._guard = None


def test_duplicate_call_within_window():
    """Same tool + same args within 5ms should be blocked."""
    guard = ToolDedupGuard(window_ms=5)
    assert guard.check("bash", {"cmd": "ls"}) is False  # first call: allow
    assert guard.check("bash", {"cmd": "ls"}) is True   # duplicate: block


def test_different_args_not_suppressed():
    """Same tool but different args should not be blocked."""
    guard = ToolDedupGuard(window_ms=5)
    assert guard.check("bash", {"cmd": "ls"}) is False
    assert guard.check("bash", {"cmd": "pwd"}) is False


def test_different_tool_name_not_suppressed():
    """Same args but different tool name should not be blocked."""
    guard = ToolDedupGuard(window_ms=5)
    assert guard.check("bash", {"cmd": "ls"}) is False
    assert guard.check("grep", {"cmd": "ls"}) is False


def test_window_expiration():
    """After the window expires, same call should be allowed again."""
    guard = ToolDedupGuard(window_ms=10)
    assert guard.check("bash", {"cmd": "ls"}) is False
    time.sleep(0.015)  # 15ms > 10ms window
    assert guard.check("bash", {"cmd": "ls"}) is False


def test_clear_resets_state():
    """clear() should reset all tracked calls."""
    guard = ToolDedupGuard(window_ms=5)
    guard.check("bash", {"cmd": "ls"})
    guard.clear()
    assert guard.check("bash", {"cmd": "ls"}) is False


def test_not_configured_returns_none():
    """Before configure_dedup is called, get_dedup_guard returns None."""
    # Reset module state
    import harness.tools.dedup_guard as mod
    mod._guard = None
    assert get_dedup_guard() is None


def test_configure_creates_guard():
    """configure_dedup should create a guard."""
    guard = configure_dedup(window_ms=5)
    assert isinstance(guard, ToolDedupGuard)
    assert get_dedup_guard() is guard


@pytest.mark.asyncio
async def test_wrap_fn_integration():
    """_wrap_fn should suppress duplicate calls on wrapped function."""
    from harness.tools.registry import ToolFactory
    from harness.tools.dedup_guard import configure_dedup
    from pydantic_ai import Tool as PydanticAITool

    configure_dedup(window_ms=50)  # wider window for test reliability

    call_count = 0

    async def my_tool(ctx, cmd: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{cmd}"

    class TestFactory(ToolFactory):
        name = "bash"
        description = "test"
        def create(self) -> PydanticAITool:
            return PydanticAITool(self._wrap_fn(my_tool, self.name), takes_ctx=True)

    factory = TestFactory()
    wrapped = factory._wrap_fn(my_tool, "bash")

    call_count = 0
    r1 = await wrapped(None, cmd="ls")
    r2 = await wrapped(None, cmd="ls")  # duplicate
    r3 = await wrapped(None, cmd="pwd")  # different args

    assert r1 == "result-ls"
    assert "dedup" in r2
    assert r3 == "result-pwd"
    assert call_count == 2  # third call was not a duplicate
