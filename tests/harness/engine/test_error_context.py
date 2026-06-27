"""Test that node.failed events carry structured error context (error_type, tool_calls_before_failure)."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from harness.api import Agent
from harness.engine.macro_graph import MacroGraphBuilder
from harness.tools.registry import ToolRegistry
from server.event_bus import EventBus


def _make_builder(bus=None):
    """Create a MacroGraphBuilder with optional event bus."""
    builder = MacroGraphBuilder(
        tool_registry=ToolRegistry(),
        event_bus=bus,
    )
    builder.workflow_id = "test-wf"
    builder._workflow_name = "test"
    return builder


def _make_parsed(prompt="Test agent.", tools=None, model=None, retries=0):
    """Create a minimal parsed agent object."""
    parsed = MagicMock()
    parsed.prompt = prompt
    parsed.tools = tools or []
    parsed.model = model
    parsed.retries = retries
    parsed.on_pass = None
    parsed.on_fail = None
    return parsed


def _agent_def(name="agent1", after=None, has_conditional_edges=False):
    """Create a minimal Agent definition."""
    agent = MagicMock()
    agent.name = name
    agent.after = after or []
    agent.tools = None
    agent.model = None
    agent.result_type = None
    agent.has_conditional_edges = has_conditional_edges
    agent.on_pass = None
    agent.on_fail = None
    agent.executor = "pydantic-ai"  # ensures make_executor takes the in-process path
    return agent


# ── Test: general exception includes error_type ─────────────────────────


@pytest.mark.asyncio
async def test_node_failed_includes_error_type():
    """When a node raises an exception, node.failed payload includes error_type."""
    bus = EventBus()
    sub_id, queue = await bus.subscribe()
    builder = _make_builder(bus)

    agent_def = _agent_def(after=["_task_placeholder"])
    parsed = _make_parsed()
    dep_map = {agent_def.name: []}

    node_func = builder._make_node_func(
        agent_def, parsed, dep_map, "/tmp/nonexistent_wf", ""
    )

    state = {
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
    }

    # Patch LLMExecutor to raise inside the try block
    mock_executor_cls = MagicMock(side_effect=ValueError("test boom"))

    with patch("harness.engine.executor_factory.LLMExecutor", mock_executor_cls):
        result = await node_func(state)

    # Drain events from the queue
    events = []
    while not queue.empty():
        events.append(await queue.get())

    failed_events = [e for e in events if e["type"] == "node.failed"]
    assert len(failed_events) >= 1, f"Expected node.failed event, got: {[e['type'] for e in events]}"

    payload = failed_events[0]["payload"]
    assert payload["error"] == "test boom"
    assert payload["error_type"] == "ValueError"
    assert payload["duration_ms"] >= 0
    assert payload["attempt"] == 1
    assert payload["will_retry"] is False

    # STATE_ERRORS keeps backward compat: plain string, not dict
    assert result["errors"][agent_def.name] == "test boom"

    await bus.unsubscribe(sub_id)


# ── Test: tool_calls_before_failure when executor has tool calls ────────


@pytest.mark.asyncio
async def test_node_failed_includes_tool_calls_before_failure():
    """When executor recorded tool calls before failure, they appear in payload."""
    bus = EventBus()
    sub_id, queue = await bus.subscribe()
    builder = _make_builder(bus)

    agent_def = _agent_def(after=["_task_placeholder"])
    parsed = _make_parsed()
    dep_map = {agent_def.name: []}

    node_func = builder._make_node_func(
        agent_def, parsed, dep_map, "/tmp/nonexistent_wf", ""
    )

    state = {
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
    }

    # Patch the LLMExecutor to have tool_calls and then raise
    mock_executor_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.tool_calls = [
        {"tool_name": "bash", "tool_args": {"command": "ls"}, "tool_result": "file.txt"},
        {"tool_name": "write_file", "tool_args": {"path": "/tmp/x"}, "tool_result": "ok"},
    ]
    mock_instance.run = MagicMock(side_effect=RuntimeError("LLM crashed"))
    mock_executor_cls.return_value = mock_instance

    with patch("harness.engine.executor_factory.LLMExecutor", mock_executor_cls):
        result = await node_func(state)

    events = []
    while not queue.empty():
        events.append(await queue.get())

    failed_events = [e for e in events if e["type"] == "node.failed"]
    assert len(failed_events) == 1

    payload = failed_events[0]["payload"]
    assert payload["error_type"] == "RuntimeError"
    assert "tool_calls_before_failure" in payload

    tc_list = payload["tool_calls_before_failure"]
    assert len(tc_list) == 2
    assert tc_list[0]["tool_name"] == "bash"
    assert tc_list[0]["tool_args"] == {"command": "ls"}
    assert tc_list[1]["tool_name"] == "write_file"

    await bus.unsubscribe(sub_id)


# ── Test: upstream failure has synthetic error_type ─────────────────────


@pytest.mark.asyncio
async def test_upstream_failure_has_synthetic_error_type():
    """When a node is skipped due to upstream failure, error_type is UpstreamDependencyError."""
    bus = EventBus()
    sub_id, queue = await bus.subscribe()
    builder = _make_builder(bus)

    agent_def = _agent_def(name="agent2", after=["agent1"])
    parsed = _make_parsed()
    dep_map = {agent_def.name: ["agent1"]}

    node_func = builder._make_node_func(
        agent_def, parsed, dep_map, "/tmp/nonexistent_wf", ""
    )

    state = {
        "inputs": {},
        "outputs": {},
        "errors": {"agent1": "some upstream error"},
        "metadata": {},
    }

    result = await node_func(state)

    events = []
    while not queue.empty():
        events.append(await queue.get())

    failed_events = [e for e in events if e["type"] == "node.failed"]
    assert len(failed_events) == 1

    payload = failed_events[0]["payload"]
    assert payload["error_type"] == "UpstreamDependencyError"
    assert "Skipped: upstream" in payload["error"]
    assert payload["duration_ms"] == 0

    await bus.unsubscribe(sub_id)


# ── Test: max iterations has synthetic error_type ───────────────────────


@pytest.mark.asyncio
async def test_max_iterations_has_synthetic_error_type():
    """When max iterations is reached, error_type is MaxIterationsError."""
    bus = EventBus()
    sub_id, queue = await bus.subscribe()
    builder = _make_builder(bus)

    agent_def = _agent_def(has_conditional_edges=True)
    parsed = _make_parsed()
    dep_map = {agent_def.name: []}

    node_func = builder._make_node_func(
        agent_def, parsed, dep_map, "/tmp/nonexistent_wf", ""
    )

    # Set iteration count to max
    state = {
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
        "iteration_counts": {f"{agent_def.name}_loop": builder.max_iterations},
    }

    result = await node_func(state)

    events = []
    while not queue.empty():
        events.append(await queue.get())

    failed_events = [e for e in events if e["type"] == "node.failed"]
    assert len(failed_events) == 1

    payload = failed_events[0]["payload"]
    assert payload["error_type"] == "MaxIterationsError"
    assert "Max iterations" in payload["error"]

    await bus.unsubscribe(sub_id)


# ── Test: no tool_calls_before_failure when executor has none ───────────


@pytest.mark.asyncio
async def test_node_failed_no_tool_calls_field_when_empty():
    """tool_calls_before_failure is absent when executor has no tool calls."""
    bus = EventBus()
    sub_id, queue = await bus.subscribe()
    builder = _make_builder(bus)

    agent_def = _agent_def(after=["_task_placeholder"])
    parsed = _make_parsed()
    dep_map = {agent_def.name: []}

    node_func = builder._make_node_func(
        agent_def, parsed, dep_map, "/tmp/nonexistent_wf", ""
    )

    state = {
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
    }

    # Patch to raise after creating executor with empty tool_calls
    mock_executor_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.tool_calls = []
    mock_instance.run = MagicMock(side_effect=RuntimeError("fail"))
    mock_executor_cls.return_value = mock_instance

    with patch("harness.engine.executor_factory.LLMExecutor", mock_executor_cls):
        result = await node_func(state)

    events = []
    while not queue.empty():
        events.append(await queue.get())

    failed_events = [e for e in events if e["type"] == "node.failed"]
    assert len(failed_events) == 1

    payload = failed_events[0]["payload"]
    assert "tool_calls_before_failure" not in payload
    assert payload["error_type"] == "RuntimeError"

    await bus.unsubscribe(sub_id)
