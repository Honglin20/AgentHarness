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
            # ctx.state.usage must be a real object with int attrs so the
            # baseline/delta arithmetic in _handle_model_request doesn't
            # choke on MagicMock - int comparisons.
            self.ctx = MagicMock()
            self.ctx.state = SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    requests=0,
                    cache_read_tokens=0,
                ),
                message_history=[],
            )
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


# ---------------------------------------------------------------------------
# Per-request usage delta (stage 2 — token stats semantic split)
# ---------------------------------------------------------------------------

class _MutableUsage:
    """Mock pydantic_ai RunUsage whose attributes mutate as the iter proceeds.

    Real Pydantic AI increments input_tokens / output_tokens after each
    model request; we simulate that by calling incr() in the stream body.
    """

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0
        self.cache_read_tokens = 0

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    def incr(self, *, input_tokens=0, output_tokens=0, cache_read_tokens=0):
        """Test helper — call inside a stream body to simulate Pydantic AI incr."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        self.requests += 1


def _make_agent_with_usage_delta(deltas):
    """Mock agent whose iter() drives N model_request nodes; each one
    increments ctx.state.usage by the corresponding delta and emits a
    stream event, simulating what Pydantic AI does on a real call.

    deltas: list of dicts like {"input": 30, "output": 5, "cache": 0}
    """
    usage = _MutableUsage()
    end_node = SimpleNamespace(__class__=type("End", (), {}))
    from pydantic_graph import End
    end_node = End("done")

    nodes = []
    for d in deltas:
        node = MagicMock()
        node._type = "model_request"
        node._delta = d
        nodes.append(node)

    class _StreamCtx:
        def __init__(self, node, ctx):
            self._node = node
            self._ctx = ctx

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def stream_response(self):
            # Simulate Pydantic AI finalizing the response: incr usage once.
            self._ctx.state.usage.incr(
                input_tokens=self._node._delta.get("input", 0),
                output_tokens=self._node._delta.get("output", 0),
                cache_read_tokens=self._node._delta.get("cache", 0),
            )
            # Yield one empty response so the stream loop runs at least once
            response = SimpleNamespace(parts=[])
            yield response

    class _MockIter:
        def __init__(self):
            self._remaining = list(nodes)
            self.next_node = self._remaining.pop(0) if self._remaining else end_node
            self.ctx = MagicMock()
            self.ctx.state = SimpleNamespace(usage=usage, message_history=[])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def next(self, node):
            if self._remaining:
                return self._remaining.pop(0)
            return end_node

    agent = MagicMock()
    agent.iter = MagicMock(return_value=_MockIter())
    agent.is_model_request_node = lambda n: getattr(n, "_type", None) == "model_request"
    agent.is_call_tools_node = lambda n: getattr(n, "_type", None) == "call_tools"

    for node in nodes:
        node.stream = lambda ctx, _node=node: _StreamCtx(_node, ctx)

    return agent, usage


@pytest.mark.asyncio
async def test_last_input_single_request():
    """One model request: last_input == cumulative_input == the only delta."""
    agent, usage = _make_agent_with_usage_delta([
        {"input": 50, "output": 10, "cache": 5},
    ])
    bus = MagicMock()
    executor = LLMExecutor(
        agent, MagicMock(),
        event_bus=bus,
        workflow_id="wf1", node_id="n1", agent_name="a1",
    )
    await executor.run("ctx")

    # Find the agent.usage_update event
    usage_events = [c for c in bus.emit.call_args_list if c.args[0] == "agent.usage_update"]
    assert len(usage_events) == 1
    payload = usage_events[0].args[1]
    assert payload["input_tokens"] == 50       # cumulative (legacy)
    assert payload["cumulative_input"] == 50   # explicit alias
    assert payload["last_input"] == 50         # single-shot
    assert payload["last_output"] == 10
    assert payload["cache_hit"] == 5
    assert payload["cumulative_cache_hit"] == 5
    assert payload["last_cache_hit"] == 5


@pytest.mark.asyncio
async def test_last_input_multi_request_is_delta():
    """Three model requests: last_input reflects ONLY the most recent,
    while cumulative_input keeps growing. This is the core fix."""
    agent, usage = _make_agent_with_usage_delta([
        {"input": 20, "output": 5, "cache": 0},
        {"input": 30, "output": 8, "cache": 0},   # cumulative 50, last 30
        {"input": 40, "output": 12, "cache": 0},  # cumulative 90, last 40
    ])
    bus = MagicMock()
    executor = LLMExecutor(
        agent, MagicMock(),
        event_bus=bus,
        workflow_id="wf1", node_id="n1", agent_name="a1",
    )
    await executor.run("ctx")

    usage_events = [c for c in bus.emit.call_args_list if c.args[0] == "agent.usage_update"]
    assert len(usage_events) == 3

    # First: cumulative 20, last 20
    assert usage_events[0].args[1]["cumulative_input"] == 20
    assert usage_events[0].args[1]["last_input"] == 20

    # Second: cumulative 50, last 30 (delta from 20→50)
    assert usage_events[1].args[1]["cumulative_input"] == 50
    assert usage_events[1].args[1]["last_input"] == 30

    # Third: cumulative 90, last 40 (delta from 50→90)
    assert usage_events[2].args[1]["cumulative_input"] == 90
    assert usage_events[2].args[1]["last_input"] == 40

    # get_last_request_usage() reflects the final request
    last = executor.get_last_request_usage()
    assert last["last_input"] == 40
    assert last["last_output"] == 12


@pytest.mark.asyncio
async def test_usage_resets_on_run_reentry():
    """Calling run() twice (e.g. via execute_with_retry) must reset baselines.
    Without this, the second attempt's last_input would carry the first
    attempt's cumulative as baseline."""
    agent, usage = _make_agent_with_usage_delta([
        {"input": 50, "output": 5, "cache": 0},
    ])
    executor = LLMExecutor(agent, MagicMock(), event_bus=None)

    await executor.run("ctx1")
    assert executor._last_input == 50

    # Reset the mock usage so the second run starts fresh (mirrors Pydantic
    # AI giving each iter() a new usage accumulator on retry).
    usage.input_tokens = 0
    usage.output_tokens = 0
    usage.requests = 0

    await executor.run("ctx2")
    # If baseline wasn't reset, last_input would be 0 - 50 = -50 (clamped).
    assert executor._last_input == 50  # the new request's delta


@pytest.mark.asyncio
async def test_cache_read_tokens_missing_defaults_to_zero():
    """Older Pydantic AI versions may lack cache_read_tokens. Must not crash."""
    usage = _MutableUsage()
    delattr(usage, "cache_read_tokens") if hasattr(usage, "cache_read_tokens") else None
    # Replace with an object that has NO cache_read_tokens attribute
    bare_usage = SimpleNamespace(
        input_tokens=0, output_tokens=0, requests=0, total_tokens=0,
    )

    from pydantic_graph import End
    end_node = End("done")

    node = MagicMock()
    node._type = "model_request"

    class _StreamCtx:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def stream_response(self):
            bare_usage.input_tokens = 30
            bare_usage.output_tokens = 5
            yield SimpleNamespace(parts=[])

    class _MockIter:
        def __init__(self):
            self.next_node = node
            self.ctx = MagicMock()
            self.ctx.state = SimpleNamespace(usage=bare_usage, message_history=[])
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def next(self, n):
            return end_node

    agent = MagicMock()
    agent.iter = MagicMock(return_value=_MockIter())
    agent.is_model_request_node = lambda n: getattr(n, "_type", None) == "model_request"
    agent.is_call_tools_node = lambda n: False
    node.stream = lambda ctx: _StreamCtx()

    bus = MagicMock()
    executor = LLMExecutor(
        agent, MagicMock(),
        event_bus=bus,
        workflow_id="wf1", node_id="n1", agent_name="a1",
    )
    await executor.run("ctx")

    usage_events = [c for c in bus.emit.call_args_list if c.args[0] == "agent.usage_update"]
    assert len(usage_events) == 1
    p = usage_events[0].args[1]
    assert p["last_input"] == 30
    assert p["cache_hit"] == 0  # missing attr → 0


def test_get_last_request_usage_returns_zero_before_any_run():
    """Fresh executor: no model request yet → all zeros."""
    agent = MagicMock()
    executor = LLMExecutor(agent, MagicMock())
    last = executor.get_last_request_usage()
    assert last == {"last_input": 0, "last_output": 0, "last_cache_hit": 0}


@pytest.mark.asyncio
async def test_negative_delta_clamps_and_emits_ext_error():
    """If usage.incr lowered input_tokens between baseline capture and exit
    (instrumentation bug, mocked behavior, or a future refactor), delta goes
    negative. Must clamp to 0 and surface ext.error so operators notice —
    silently propagating negative numbers to the UI would be worse.
    """
    from pydantic_graph import End
    end_node = End("done")

    node = MagicMock()
    node._type = "model_request"

    # Mutable usage that drops between baseline capture (entry) and exit.
    # First read at entry returns 100; stream_response flips it to 50; the
    # exit read sees 50 → delta = 50 - 100 = -50.
    usage = SimpleNamespace(
        input_tokens=100, output_tokens=20, requests=1,
        total_tokens=120, cache_read_tokens=0,
    )

    class _StreamCtx:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def stream_response(self):
            # Flip usage to a value LOWER than baseline to force negative delta.
            usage.input_tokens = 50
            usage.output_tokens = 10
            yield SimpleNamespace(parts=[])

    class _MockIter:
        def __init__(self):
            self.next_node = node
            self.ctx = MagicMock()
            self.ctx.state = SimpleNamespace(usage=usage, message_history=[])
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def next(self, n):
            return end_node

    agent = MagicMock()
    iter_ctx = _MockIter()
    agent.iter = MagicMock(return_value=iter_ctx)
    agent.is_model_request_node = lambda n: getattr(n, "_type", None) == "model_request"
    agent.is_call_tools_node = lambda n: False
    node.stream = lambda ctx: _StreamCtx()

    bus = MagicMock()
    executor = LLMExecutor(
        agent, MagicMock(),
        event_bus=bus,
        workflow_id="wf1", node_id="n1", agent_name="a1",
    )
    # Bypass run()'s reset by calling _handle_model_request directly so
    # our mock usage values flow through unchanged.
    await executor._handle_model_request(node, iter_ctx.ctx)

    # ext.error emitted with the diagnostic
    error_events = [c for c in bus.emit.call_args_list if c.args[0] == "ext.error"]
    assert len(error_events) == 1
    assert "negative usage delta" in error_events[0].args[1]["error"]

    # Last values clamped to 0, not negative
    last = executor.get_last_request_usage()
    assert last["last_input"] == 0
    assert last["last_output"] == 0


# ── _build_schema_retry_reminder: schema-recovery reminder after RetryPromptPart ──


class TestSchemaRetryReminder:
    """Regression: 2026-06-17 adapter_generator incident.

    When the model emits text/markdown instead of a ``final_result`` tool
    call, pydantic-ai appends a ``RetryPromptPart`` to message_history
    with a terse "Invalid JSON" message. Models that drifted into
    markdown-summary mode often couldn't recover because the feedback
    didn't name the tool or show the expected schema.

    LLMExecutor._build_schema_retry_reminder detects this case and emits
    a fresh reminder naming ``final_result`` + dumping the schema.
    """

    def _make_executor(self, output_type):
        from harness.engine.llm_executor import LLMExecutor
        from pydantic_ai import Agent
        agent = Agent(output_type=output_type, retries={"tools": 0, "output": 2}, defer_model_check=True)

        class _Fe(LLMExecutor):
            def __init__(self, ag):
                self._agent = ag
                self._agent_name = "adapter_generator"
        return _Fe(agent)

    def test_empty_history_returns_none(self):
        from pydantic import BaseModel
        class Out(BaseModel):
            x: int
        ex = self._make_executor(Out)
        assert ex._build_schema_retry_reminder([]) is None

    def test_no_retry_prompt_returns_none(self):
        from pydantic import BaseModel
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        class Out(BaseModel):
            x: int
        ex = self._make_executor(Out)
        history = [ModelRequest(parts=[UserPromptPart(content="hi")])]
        assert ex._build_schema_retry_reminder(history) is None

    def test_retry_prompt_triggers_reminder_with_tool_name_and_schema(self):
        from pydantic import BaseModel, Field
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, RetryPromptPart, UserPromptPart
        class AdapterGenResult(BaseModel):
            summary: str
            adapter_path: str = Field(description="Absolute path")
            smoke_pass: bool

        ex = self._make_executor(AdapterGenResult)
        history = [
            ModelRequest(parts=[UserPromptPart(content="Generate adapter.")]),
            ModelResponse(parts=[TextPart(content="Adapter:\n## Done\nGenerated.")]),
            ModelRequest(parts=[RetryPromptPart(content=[{"type": "json_invalid", "loc": [], "msg": "Invalid JSON"}])]),
        ]
        reminder = ex._build_schema_retry_reminder(history)
        assert reminder is not None
        # Names the tool explicitly
        assert "`final_result`" in reminder
        # Shows the expected schema (all three required fields surface)
        assert "summary" in reminder
        assert "adapter_path" in reminder
        assert "smoke_pass" in reminder
        # Tells the model not to emit text — the core instruction that was
        # missing from pydantic-ai's default "Invalid JSON" feedback.
        assert "tool call" in reminder.lower()

    def test_free_text_agent_returns_none(self):
        """Agents with str output_type have no schema to remind about."""
        from pydantic_ai.messages import ModelRequest, RetryPromptPart
        ex = self._make_executor(str)
        history = [ModelRequest(parts=[RetryPromptPart(content=[{"type": "x", "loc": [], "msg": "y"}])])]
        assert ex._build_schema_retry_reminder(history) is None
