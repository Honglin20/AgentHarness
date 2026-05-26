"""Tests for LLMExecutor — agent iteration loop with streaming + interrupts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harness.engine.llm_executor import AgentRunResult, LLMExecutor


# ---------------------------------------------------------------------------
# Helpers to mock pydantic_ai agent iteration
# ---------------------------------------------------------------------------

def _make_mock_agent_run(output="done", nodes=None):
    """Create a mock AgentRun that yields the given nodes then ends."""
    if nodes is None:
        nodes = []

    ctx = MagicMock()

    class MockIter:
        def __init__(self):
            self.next_node = nodes.pop(0) if nodes else SimpleNamespace()
            self._nodes = nodes
            self.result = SimpleNamespace(output=output, usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def next(self, node):
            if self._nodes:
                return self._nodes.pop(0)
            # Return End sentinel
            from pydantic_graph import End
            return End("done")

    return MockIter()


class EndSentinel:
    """Minimal End sentinel."""
    pass


def _make_agent_with_nodes(node_types):
    """Create a mock pydantic agent that iter() returns specific node types.

    node_types: list of ("model_request" | "call_tools" | "other")
    """
    agent = MagicMock()

    # Build node objects
    nodes = []
    for nt in node_types:
        node = MagicMock()
        if nt == "model_request":
            node._type = "model_request"
        elif nt == "call_tools":
            node._type = "call_tools"
        else:
            node._type = "other"
        nodes.append(node)

    # End sentinel — isinstance check uses pydantic_graph.End
    from pydantic_graph import End
    end_node = End("done")

    class MockIterCtx:
        def __init__(self):
            self._remaining = list(nodes)
            self.next_node = self._remaining.pop(0) if self._remaining else end_node
            self.ctx = MagicMock()
            self.result = SimpleNamespace(output="test_output", usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def next(self, node):
            if self._remaining:
                return self._remaining.pop(0)
            return end_node

    agent.iter = MagicMock(return_value=MockIterCtx())
    agent.is_model_request_node = lambda n: getattr(n, '_type', None) == 'model_request'
    agent.is_call_tools_node = lambda n: getattr(n, '_type', None) == 'call_tools'

    # Mock stream for model_request nodes
    def _mock_model_stream(node, ctx):
        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.stream_response = MagicMock(return_value=_async_iter([]))
        return mock_stream

    # Mock stream for call_tools nodes
    def _mock_tool_stream(node, ctx):
        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.__aiter__ = lambda self: _async_iter([])
        mock_stream.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
        return mock_stream

    # Monkey-patch node.stream to return mock streams
    for node in nodes:
        if node._type == "model_request":
            node.stream = _mock_model_stream
        elif node._type == "call_tools":
            node.stream = _mock_tool_stream

    return agent


async def _async_iter(items):
    """Helper: async iterator over a list."""
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_returns_agent_output():
    """Basic: LLMExecutor returns the agent's output."""
    agent = _make_agent_with_nodes([])
    executor = LLMExecutor(agent, deps=MagicMock())
    result = await executor.run("hello")

    assert result.stop_regen is None
    assert result.agent_run.result.output == "test_output"


@pytest.mark.asyncio
async def test_emit_text_delta():
    """Text deltas are emitted via bus when model streams."""
    bus = MagicMock()
    agent = _make_agent_with_nodes(["model_request"])
    node = MagicMock()
    node._type = "model_request"

    # Override stream to produce text
    async def mock_stream_response():
        part = SimpleNamespace(content="Hello world", part_kind="text")
        response = SimpleNamespace(parts=[part])
        yield response

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_stream_ctx.stream_response = mock_stream_response

    for n in [n for n in agent.iter().__class__.__mro__]:
        pass

    # Access the mock iter context and patch node.stream
    iter_ctx = agent.iter()
    # Find the model_request node and patch its stream
    from pydantic_graph import End
    first_node = iter_ctx.next_node
    if hasattr(first_node, '_type') and first_node._type == 'model_request':
        first_node.stream = MagicMock(return_value=mock_stream_ctx)

    executor = LLMExecutor(
        agent, MagicMock(),
        event_bus=bus,
        workflow_id="wf1",
        node_id="n1",
        agent_name="a1",
    )
    result = await executor.run("hello")
    # Bus should have been called with agent.text_delta
    assert any(
        call.args[0] == "agent.text_delta"
        for call in bus.emit.call_args_list
    )


@pytest.mark.asyncio
async def test_interrupt_triggers_callback():
    """If check_interrupt returns a signal, run() returns it as stop_regen."""
    signal = {"agent_name": "a1", "partial_output": "partial", "user_guidance": "fix it"}
    check_fn = MagicMock(return_value=signal)
    cancel_fn = MagicMock()

    agent = _make_agent_with_nodes(["model_request"])
    iter_ctx = agent.iter()

    # Patch model_request node stream to produce text so interrupt is polled
    async def mock_stream_response():
        part = SimpleNamespace(content="some text", part_kind="text")
        response = SimpleNamespace(parts=[part])
        yield response

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_stream_ctx.stream_response = mock_stream_response

    from pydantic_graph import End
    first_node = iter_ctx.next_node
    if hasattr(first_node, '_type') and first_node._type == 'model_request':
        first_node.stream = MagicMock(return_value=mock_stream_ctx)

    executor = LLMExecutor(
        agent, MagicMock(),
        workflow_id="wf1",
        node_id="n1",
        agent_name="a1",
        check_interrupt=check_fn,
        cancel_fn=cancel_fn,
    )
    result = await executor.run("hello")

    assert result.stop_regen == signal
    cancel_fn.assert_called_with("wf1")


@pytest.mark.asyncio
async def test_no_interrupt_returns_none():
    """When check_interrupt always returns None, stop_regen is None."""
    check_fn = MagicMock(return_value=None)
    agent = _make_agent_with_nodes([])
    executor = LLMExecutor(
        agent, MagicMock(),
        check_interrupt=check_fn,
    )
    result = await executor.run("hello")
    assert result.stop_regen is None


@pytest.mark.asyncio
async def test_no_bus_no_events():
    """Without a bus, no events are emitted (no crash)."""
    agent = _make_agent_with_nodes(["model_request"])
    iter_ctx = agent.iter()

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_stream_ctx.stream_response = MagicMock(return_value=_async_iter([]))

    first_node = iter_ctx.next_node
    if hasattr(first_node, '_type') and first_node._type == 'model_request':
        first_node.stream = MagicMock(return_value=mock_stream_ctx)

    executor = LLMExecutor(agent, MagicMock())
    result = await executor.run("hello")

    assert result.stop_regen is None
    assert result.agent_run is not None
