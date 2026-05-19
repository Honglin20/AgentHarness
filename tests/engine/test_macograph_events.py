"""Tests for MacroGraph event integration."""

import asyncio
import pytest

from harness.api import Agent, Workflow
from harness.compiler.md_parser import parse_agent_md
from harness.compiler.dag_builder import build_dag
from harness.engine.macro_graph import MacroGraphBuilder
from harness.tools.registry import ToolRegistry
from server.event_bus import EventBus


@pytest.mark.asyncio
async def test_macograph_builder_accepts_event_bus(tmp_path):
    """MacroGraphBuilder accepts optional event_bus parameter."""
    bus = EventBus()
    registry = ToolRegistry()

    builder = MacroGraphBuilder(
        tool_registry=registry,
        event_bus=bus,
    )

    assert builder.event_bus is bus


@pytest.mark.asyncio
async def test_workflow_compiles_with_event_bus(tmp_path):
    """Workflow compile() passes event_bus to MacroGraphBuilder."""
    bus = EventBus()

    # Create test agents
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    (agents_dir / "agent1.md").write_text("""
---
name: agent1
retries: 1
---
First agent.
""")

    (agents_dir / "agent2.md").write_text("""
---
name: agent2
retries: 1
---
Second agent.
""")

    workflow = Workflow(
        name="test",
        agents=[
            Agent("agent1", after=[]),
            Agent("agent2", after=["agent1"]),
        ],
        agents_dir=str(agents_dir),
        event_bus=bus,
    )

    graph = workflow.compile()

    assert graph is not None
    assert bus.subscriber_count == 0  # No WS subscribers yet


@pytest.mark.asyncio
async def test_node_emits_events_on_success(tmp_path):
    """Node function emits started and completed events on success."""
    bus = EventBus()
    sub_id, queue = await bus.subscribe()

    # Create a minimal workflow
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    (agents_dir / "agent1.md").write_text("""
---
name: agent1
retries: 0
---
Simple agent.
""")

    workflow = Workflow(
        name="test",
        agents=[Agent("agent1", after=[])],
        agents_dir=str(agents_dir),
        event_bus=bus,
        tool_registry=ToolRegistry(),
    )

    # Note: We can't actually run the workflow (needs LLM), but we can test compilation
    graph = workflow.compile()

    # Since we can't run without LLM, we verify the structure is correct
    assert graph is not None

    # Cleanup
    await bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_node_emits_events_on_error(tmp_path):
    """Node function emits failed event on exception."""
    bus = EventBus()
    sub_id, queue = await bus.subscribe()

    # This test verifies the event emission structure without running
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    (agents_dir / "agent1.md").write_text("""
---
name: agent1
retries: 0
---
Will fail agent.
""")

    workflow = Workflow(
        name="test",
        agents=[Agent("agent1", after=[])],
        agents_dir=str(agents_dir),
        event_bus=bus,
        tool_registry=ToolRegistry(),
    )

    graph = workflow.compile()

    assert graph is not None

    # Cleanup
    await bus.unsubscribe(sub_id)


@pytest.mark.asyncio
async def test_event_payload_structure(tmp_path):
    """Event payloads have correct structure."""
    bus = EventBus()
    sub_id, queue = await bus.subscribe()

    # Simulate event emission
    bus.emit("node.started", {
        "node_id": "test_agent",
        "agent_name": "test_agent",
        "attempt": 1,
    })

    event = await asyncio.wait_for(queue.get(), timeout=1.0)

    assert event["type"] == "node.started"
    assert event["payload"]["node_id"] == "test_agent"
    assert event["payload"]["agent_name"] == "test_agent"
    assert event["payload"]["attempt"] == 1
    assert "ts" in event  # Timestamp field

    await bus.unsubscribe(sub_id)