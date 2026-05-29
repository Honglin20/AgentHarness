"""Tests for span tracing (span.start / span.end) and TTFT measurement."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from harness.engine.llm_executor import AgentRunResult, LLMExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeBus:
    """Collects emitted events for assertions."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict):
        self.events.append((event_type, payload))


def _make_part(tool_name, args=None, content=""):
    part = MagicMock()
    part.tool_name = tool_name
    part.args = args or {}
    part.content = content
    return part


# ---------------------------------------------------------------------------
# Span tracing: LLM calls
# ---------------------------------------------------------------------------

class TestLLMSpanTracing:
    """span.start and span.end events for LLM (model-request) nodes."""

    def test_llm_span_start_and_end_emitted(self):
        """LLMExecutor emits span.start before streaming and span.end after."""
        bus = _FakeBus()
        agent_mock = MagicMock()
        agent_mock.model = MagicMock()
        agent_mock.model.model_name = "test-model"

        executor = LLMExecutor(
            agent_mock, MagicMock(),
            event_bus=bus, workflow_id="wf1", node_id="node1", agent_name="agent1",
        )

        span_start_called = False
        span_end_called = False

        # Patch the async context managers to simulate streaming
        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        # Simulate one response part with text
        text_part = MagicMock()
        text_part.part_kind = "text"
        text_part.content = "hello world"

        response = MagicMock()
        response.parts = [text_part]

        mock_stream.stream_response = MagicMock(return_value=_async_iter([response]))

        mock_node = MagicMock()
        mock_node.stream = MagicMock(return_value=mock_stream)

        result = asyncio.get_event_loop().run_until_complete(
            executor._handle_model_request(mock_node, MagicMock())
        )

        # Should have span.start and span.end
        span_starts = [e for e in bus.events if e[0] == "span.start"]
        span_ends = [e for e in bus.events if e[0] == "span.end"]

        assert len(span_starts) == 1
        assert len(span_ends) == 1

        start_payload = span_starts[0][1]
        assert start_payload["span_type"] == "llm"
        assert start_payload["span_id"] == "node1-s1"
        assert start_payload["workflow_id"] == "wf1"
        assert start_payload["node_id"] == "node1"
        assert start_payload["agent_name"] == "agent1"
        assert start_payload["model"] == "test-model"

        end_payload = span_ends[0][1]
        assert end_payload["span_type"] == "llm"
        assert end_payload["span_id"] == "node1-s1"

    def test_llm_span_no_emit_without_bus(self):
        """No span events when bus is None."""
        executor = LLMExecutor(
            MagicMock(), MagicMock(),
            event_bus=None, workflow_id="wf1", node_id="node1", agent_name="agent1",
        )

        # Just verify no exception
        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.stream_response = MagicMock(return_value=_async_iter([]))

        mock_node = MagicMock()
        mock_node.stream = MagicMock(return_value=mock_stream)

        asyncio.get_event_loop().run_until_complete(
            executor._handle_model_request(mock_node, MagicMock())
        )


# ---------------------------------------------------------------------------
# Span tracing: tool calls
# ---------------------------------------------------------------------------

class TestToolSpanTracing:
    """span.start and span.end events for tool-call nodes."""

    def test_tool_span_start_and_end_emitted(self):
        """LLMExecutor emits span.start on tool call and span.end on tool result."""
        bus = _FakeBus()
        executor = LLMExecutor(
            MagicMock(), MagicMock(),
            event_bus=bus, workflow_id="wf1", node_id="node1", agent_name="agent1",
        )

        # Create tool call event
        call_part = _make_part("bash", args={"command": "ls"})
        call_event = MagicMock()
        call_event.event_kind = "function_tool_call"
        call_event.part = call_part

        # Create tool result event
        result_part = _make_part("bash", content="file.txt")
        result_event = MagicMock()
        result_event.event_kind = "function_tool_result"
        result_event.part = result_part

        # The code sets _span_call_key on the call_part, then reads it from
        # result_part. We bridge them by making result_part._span_call_key
        # dynamically read from call_part.
        type(result_part)._span_call_key = property(
            lambda self: getattr(call_part, "_span_call_key", None),
        )

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.__aiter__ = MagicMock(return_value=_async_iter([call_event, result_event]))

        mock_node = MagicMock()
        mock_node.stream = MagicMock(return_value=mock_stream)

        executor._fire_tool_call_hook = AsyncMock()

        asyncio.get_event_loop().run_until_complete(
            executor._handle_call_tools(mock_node, MagicMock())
        )

        span_starts = [e for e in bus.events if e[0] == "span.start"]
        span_ends = [e for e in bus.events if e[0] == "span.end"]

        assert len(span_starts) == 1
        assert len(span_ends) == 1

        start_payload = span_starts[0][1]
        assert start_payload["span_type"] == "tool"
        assert start_payload["tool_name"] == "bash"
        assert "span_id" in start_payload

        end_payload = span_ends[0][1]
        assert end_payload["span_type"] == "tool"
        assert end_payload["tool_name"] == "bash"
        assert end_payload["span_id"] == start_payload["span_id"]

        # Clean up the property we added
        del type(result_part)._span_call_key

    def test_tool_span_multiple_calls(self):
        """Multiple tool calls produce separate span IDs."""
        bus = _FakeBus()
        executor = LLMExecutor(
            MagicMock(), MagicMock(),
            event_bus=bus, workflow_id="wf1", node_id="node1", agent_name="agent1",
        )

        # Two tool calls
        call_part1 = _make_part("bash", args={"command": "ls"})
        call_event1 = MagicMock()
        call_event1.event_kind = "function_tool_call"
        call_event1.part = call_part1

        call_part2 = _make_part("read_file", args={"path": "/tmp/x"})
        call_event2 = MagicMock()
        call_event2.event_kind = "function_tool_call"
        call_event2.part = call_part2

        # Two results
        result_part1 = _make_part("bash", content="file.txt")
        result_event1 = MagicMock()
        result_event1.event_kind = "function_tool_result"
        result_event1.part = result_part1

        result_part2 = _make_part("read_file", content="content")
        result_event2 = MagicMock()
        result_event2.event_kind = "function_tool_result"
        result_event2.part = result_part2

        # Bridge: result parts dynamically read _span_call_key from their
        # corresponding call parts (set by the production code at runtime).
        type(result_part1)._span_call_key = property(
            lambda self: getattr(call_part1, "_span_call_key", None),
        )
        type(result_part2)._span_call_key = property(
            lambda self: getattr(call_part2, "_span_call_key", None),
        )

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.__aiter__ = MagicMock(
            return_value=_async_iter([call_event1, call_event2, result_event1, result_event2])
        )

        mock_node = MagicMock()
        mock_node.stream = MagicMock(return_value=mock_stream)

        executor._fire_tool_call_hook = AsyncMock()

        asyncio.get_event_loop().run_until_complete(
            executor._handle_call_tools(mock_node, MagicMock())
        )

        span_starts = [e for e in bus.events if e[0] == "span.start"]
        span_ends = [e for e in bus.events if e[0] == "span.end"]

        assert len(span_starts) == 2
        assert len(span_ends) == 2

        # Verify distinct span IDs
        start_ids = {e[1]["span_id"] for e in span_starts}
        end_ids = {e[1]["span_id"] for e in span_ends}
        assert start_ids == end_ids
        assert len(start_ids) == 2

        # Clean up
        del type(result_part1)._span_call_key
        del type(result_part2)._span_call_key


# ---------------------------------------------------------------------------
# TTFT measurement
# ---------------------------------------------------------------------------

class TestTTFT:
    """Time-to-first-token is measured and returned in AgentRunResult."""

    def test_ttft_measured_on_text_delta(self):
        """TTFT is set when the first text delta arrives."""
        bus = _FakeBus()
        agent_mock = MagicMock()
        agent_mock.model = MagicMock()
        agent_mock.model.model_name = "test-model"

        executor = LLMExecutor(
            agent_mock, MagicMock(),
            event_bus=bus, workflow_id="wf1", node_id="node1", agent_name="agent1",
        )

        text_part = MagicMock()
        text_part.part_kind = "text"
        text_part.content = "first"

        response = MagicMock()
        response.parts = [text_part]

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.stream_response = MagicMock(return_value=_async_iter([response]))

        mock_node = MagicMock()
        mock_node.stream = MagicMock(return_value=mock_stream)

        asyncio.get_event_loop().run_until_complete(
            executor._handle_model_request(mock_node, MagicMock())
        )

        assert executor._last_ttft_ms is not None
        assert executor._last_ttft_ms >= 0

    def test_ttft_none_when_no_tokens(self):
        """TTFT stays None when no tokens are produced."""
        executor = LLMExecutor(
            MagicMock(), MagicMock(),
            event_bus=None, workflow_id="wf1", node_id="node1", agent_name="agent1",
        )

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.stream_response = MagicMock(return_value=_async_iter([]))

        mock_node = MagicMock()
        mock_node.stream = MagicMock(return_value=mock_stream)

        asyncio.get_event_loop().run_until_complete(
            executor._handle_model_request(mock_node, MagicMock())
        )

        assert executor._last_ttft_ms is None

    def test_ttft_in_agent_run_result(self):
        """AgentRunResult carries ttft_ms from the executor."""
        result = AgentRunResult(agent_run=MagicMock(), ttft_ms=42)
        assert result.ttft_ms == 42

    def test_ttft_default_none(self):
        """AgentRunResult defaults ttft_ms to None."""
        result = AgentRunResult(agent_run=MagicMock())
        assert result.ttft_ms is None


# ---------------------------------------------------------------------------
# Span ID generation
# ---------------------------------------------------------------------------

class TestSpanIdGeneration:
    """_next_span_id generates unique, sequential span IDs."""

    def test_span_ids_sequential(self):
        executor = LLMExecutor(
            MagicMock(), MagicMock(),
            event_bus=None, workflow_id="wf1", node_id="my-node", agent_name="a1",
        )
        assert executor._next_span_id() == "my-node-s1"
        assert executor._next_span_id() == "my-node-s2"
        assert executor._next_span_id() == "my-node-s3"

    def test_span_ids_different_nodes(self):
        """Different node IDs produce different prefixes."""
        e1 = LLMExecutor(
            MagicMock(), MagicMock(),
            event_bus=None, workflow_id="wf1", node_id="node-a", agent_name="a1",
        )
        e2 = LLMExecutor(
            MagicMock(), MagicMock(),
            event_bus=None, workflow_id="wf1", node_id="node-b", agent_name="a2",
        )
        assert e1._next_span_id() == "node-a-s1"
        assert e2._next_span_id() == "node-b-s1"


# ---------------------------------------------------------------------------
# Async iterator helper
# ---------------------------------------------------------------------------

class _async_iter:
    """Simple async iterator wrapper for a list."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration
