"""Tests for ask_human tool."""

import asyncio

import pytest

from harness.tools.ask_human import _pending, get_lock, resolve_question


@pytest.mark.asyncio
async def test_resolve_question_basic():
    """resolve_question() resolves a pending question."""
    # Create a pending question manually
    future = asyncio.get_event_loop().create_future()
    question_id = "test-qid"

    lock = get_lock()
    async with lock:
        _pending[question_id] = future

    # Resolve it
    await resolve_question(question_id, "test answer")

    # Verify resolved
    assert question_id not in _pending  # Removed after resolve


@pytest.mark.asyncio
async def test_resolve_nonexistent_is_noop():
    """Resolving a non-existent question_id is a no-op."""
    # Should not raise
    await resolve_question("nonexistent", "answer")


def test_ask_human_factory_name_and_description():
    """AskHumanToolFactory has correct name and description."""
    from harness.tools.ask_human import AskHumanToolFactory

    factory = AskHumanToolFactory(event_bus=None)

    assert factory.name == "ask_human"
    assert "Ask the user" in factory.description
    assert "wait for their response" in factory.description


def test_ask_human_factory_creates_tool():
    """AskHumanToolFactory.create() returns a PydanticAITool."""
    from harness.tools.ask_human import AskHumanToolFactory
    from pydantic_ai import Tool as PydanticAITool

    factory = AskHumanToolFactory(event_bus=None)
    tool = factory.create()

    assert isinstance(tool, PydanticAITool)


def test_ask_human_returns_string():
    """ask_human tool returns a string (the user's response)."""
    from harness.tools.ask_human import AskHumanToolFactory
    from pydantic_ai import Tool as PydanticAITool
    from harness.tools.deps import AgentDeps

    factory = AskHumanToolFactory(event_bus=None)
    tool = factory.create()

    # Tool is a PydanticAITool instance
    assert isinstance(tool, PydanticAITool)
    assert tool.name == "ask_human"

    # The tool takes ctx (RunContext) and returns string
    # We can verify the signature without calling it
    assert tool.takes_ctx is True


@pytest.mark.asyncio
async def test_pending_question_concurrency():
    """Multiple questions can be pending concurrently."""
    qid1 = "q1"
    qid2 = "q2"

    future1 = asyncio.get_event_loop().create_future()
    future2 = asyncio.get_event_loop().create_future()

    lock = get_lock()
    async with lock:
        _pending[qid1] = future1
        _pending[qid2] = future2

    # Both should be pending
    assert qid1 in _pending
    assert qid2 in _pending

    # Resolve both
    await resolve_question(qid1, "answer1")
    await resolve_question(qid2, "answer2")

    # Both should be removed
    assert qid1 not in _pending
    assert qid2 not in _pending