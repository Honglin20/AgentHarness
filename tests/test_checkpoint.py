"""Tests for checkpoint creation, listing, and resume."""

import asyncio
import pytest
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from harness.checkpoint import CheckpointManager


@pytest.fixture
async def checkpointer():
    """Create an in-memory AsyncSqliteSaver for testing."""
    cm = AsyncSqliteSaver.from_conn_string(":memory:")
    cp = await cm.__aenter__()
    await cp.setup()
    yield cp
    await cm.__aexit__(None, None, None)


def _build_simple_graph():
    """Build a simple 3-node linear graph for testing."""
    def node_a(state):
        return {"steps": state.get("steps", []) + ["a"]}

    def node_b(state):
        return {"steps": state.get("steps", []) + ["b"]}

    def node_c(state):
        return {"steps": state.get("steps", []) + ["c"]}

    sg = StateGraph(dict)
    sg.add_node("a", node_a)
    sg.add_node("b", node_b)
    sg.add_node("c", node_c)
    sg.add_edge("__start__", "a")
    sg.add_edge("a", "b")
    sg.add_edge("b", "c")
    sg.add_edge("c", END)
    return sg


@pytest.mark.asyncio
async def test_checkpoint_per_node(checkpointer):
    """Each node execution creates a checkpoint."""
    graph = _build_simple_graph()
    compiled = graph.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-1"}}
    result = await compiled.ainvoke({"steps": []}, config=config)
    assert result["steps"] == ["a", "b", "c"]

    # Should have checkpoints: __start__, after a, after b, after c, final
    states = []
    async for state in compiled.aget_state_history(config):
        states.append(state)

    # 5 states: __start__ + after a + after b + after c + final
    assert len(states) == 5
    assert states[0].next == ()  # final state
    assert states[1].next == ("c",)
    assert states[2].next == ("b",)
    assert states[3].next == ("a",)
    assert states[4].next == ("__start__",)


@pytest.mark.asyncio
async def test_resume_from_checkpoint(checkpointer):
    """Resume from mid-graph checkpoint only executes remaining nodes."""
    graph = _build_simple_graph()
    compiled = graph.compile(checkpointer=checkpointer)

    # Run fully first
    config = {"configurable": {"thread_id": "test-2"}}
    result = await compiled.ainvoke({"steps": []}, config=config)
    assert result["steps"] == ["a", "b", "c"]

    # Find checkpoint after node_a (next = b)
    states = []
    async for state in compiled.aget_state_history(config):
        states.append(state)

    mid = [s for s in states if s.next == ("b",)][0]
    assert mid.values["steps"] == ["a"]

    # Resume from that checkpoint
    resumed = await compiled.ainvoke(None, config=mid.config)
    assert resumed["steps"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_checkpoint_manager_list():
    """CheckpointManager.list_checkpoints returns ordered list."""
    mgr = CheckpointManager(db_path=":memory:")
    cp = await mgr.get_checkpointer()

    graph = _build_simple_graph()
    compiled = graph.compile(checkpointer=cp)

    config = {"configurable": {"thread_id": "mgr-test"}}
    await compiled.ainvoke({"steps": []}, config=config)

    checkpoints = await mgr.list_checkpoints(compiled, "mgr-test")
    assert len(checkpoints) == 5

    # First checkpoint should be final (no next_nodes)
    assert checkpoints[0]["next_nodes"] == []
    # Should have a checkpoint with next_nodes = ["b"]
    assert any(cp["next_nodes"] == ["b"] for cp in checkpoints)

    await mgr.close()


@pytest.mark.asyncio
async def test_checkpoint_manager_latest():
    """get_latest_checkpoint_config returns first non-final checkpoint."""
    mgr = CheckpointManager(db_path=":memory:")
    cp = await mgr.get_checkpointer()

    graph = _build_simple_graph()
    compiled = graph.compile(checkpointer=cp)

    config = {"configurable": {"thread_id": "latest-test"}}
    await compiled.ainvoke({"steps": []}, config=config)

    latest = await mgr.get_latest_checkpoint_config(compiled, "latest-test")
    assert latest is not None
    assert latest["configurable"]["thread_id"] == "latest-test"
    assert "checkpoint_id" in latest["configurable"]

    await mgr.close()
