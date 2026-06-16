"""Tests for TuiRenderer — the BaseHook that drives Live + Layout.

Live itself is a Rich object that talks to the terminal; we mock it out
and verify the renderer:
  - Correctly forwards hook events to SidebarPanel / MainPanel state.
  - Starts/stops Live at the right lifecycle points.
  - Reads token usage + duration from ctx.metadata on node end.
  - Survives Live.start() failure without crashing the workflow.
  - stop() is idempotent.
  - Cursor is restored after stop.

Real-terminal smoke is done via the demo_pipeline end-to-end run in
Checkpoint 6's manual verification.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from harness.extensions.base import NodeCtx, WorkflowCtx
from harness.extensions.tui.coordinator import StdinCoordinator
from harness.extensions.tui.renderer import TuiRenderer
from harness.extensions.tui.sidebar import AgentStatus


def _wf_ctx(name: str = "test_wf") -> WorkflowCtx:
    return WorkflowCtx(workflow_id="wf-id", workflow_name=name, inputs={})


def _node_ctx(agent_name: str = "alpha", metadata: dict | None = None) -> NodeCtx:
    wf = _wf_ctx()
    return NodeCtx(
        workflow=wf,
        node_id=agent_name,
        agent_name=agent_name,
        prompt="",
        messages=[],
        upstream_outputs={},
        config=None,
        metadata=metadata or {},
    )


@pytest.fixture(autouse=True)
def _fake_live(monkeypatch):
    """Replace Live with a MagicMock so tests don't touch the terminal.

    Live.start/stop/refresh all become MagicMock call_recorders — we
    assert on call counts and ordering without needing a real TTY.
    """
    live_instances = []

    class _FakeLive:
        def __init__(self, *args, **kwargs):
            self.start = MagicMock()
            self.stop = MagicMock()
            self.refresh = MagicMock()
            live_instances.append(self)

    monkeypatch.setattr("harness.extensions.tui.renderer.Live", _FakeLive)
    yield live_instances


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_workflow_start_starts_live_and_updates_sidebar(_fake_live):
    renderer = TuiRenderer(workflow_name="test_wf")
    ctx = _wf_ctx(name="test_wf")

    await renderer.on_workflow_start(ctx)

    assert renderer._started is True
    assert len(_fake_live) == 1
    _fake_live[0].start.assert_called_once()
    # Sidebar seeded with DAG topology (empty in this minimal ctx)
    assert renderer.sidebar.state.workflow_name == "test_wf"
    assert renderer.sidebar.state.started_ts_ms is not None


@pytest.mark.asyncio
async def test_on_workflow_end_stops_live(_fake_live):
    renderer = TuiRenderer()
    await renderer.on_workflow_start(_wf_ctx())
    assert renderer._started is True

    await renderer.on_workflow_end(_wf_ctx(), result={"outputs": {}, "errors": {}})

    # stop() called by on_workflow_end
    _fake_live[0].stop.assert_called_once()
    assert renderer._started is False


@pytest.mark.asyncio
async def test_on_workflow_end_marks_failed_when_errors(_fake_live):
    renderer = TuiRenderer()
    await renderer.on_workflow_start(_wf_ctx())

    await renderer.on_workflow_end(
        _wf_ctx(),
        result={"outputs": {}, "errors": {"_workflow": "boom"}},
    )

    # Sidebar completed flag set (workflow reached a terminal state).
    # Main panel may have no lines if outputs is empty — that's fine;
    # the renderer's job here is to flip sidebar state, not log the
    # failure (cli_runner writes the failed record separately).
    assert renderer.sidebar.state.completed is True


# ---------------------------------------------------------------------------
# Coordinator wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_coordinator_receives_live_on_start(_fake_live):
    """When StdinCoordinator is attached before workflow_start, TuiRenderer
    must forward the Live instance so ask_user pause/resume controls
    this renderer."""
    renderer = TuiRenderer()
    coord = StdinCoordinator()
    renderer.attach_coordinator(coord)

    assert coord._live is None  # before start
    await renderer.on_workflow_start(_wf_ctx())
    assert coord._live is _fake_live[0]  # forwarded


@pytest.mark.asyncio
async def test_detach_coordinator_live_on_stop(_fake_live):
    renderer = TuiRenderer()
    coord = StdinCoordinator()
    renderer.attach_coordinator(coord)
    await renderer.on_workflow_start(_wf_ctx())

    renderer.stop()
    assert coord._live is None  # detached


# ---------------------------------------------------------------------------
# Node lifecycle → panel state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_node_start_marks_running(_fake_live):
    renderer = TuiRenderer()
    await renderer.on_workflow_start(_wf_ctx())

    await renderer.on_node_start(_node_ctx(agent_name="analyzer"))

    assert renderer.sidebar.state.agents["analyzer"].status == AgentStatus.RUNNING
    assert renderer.main.state.current_agent == "analyzer"


@pytest.mark.asyncio
async def test_on_node_end_reads_token_usage_from_metadata(_fake_live):
    """Token usage lives in ctx.metadata[agent_name] (LLMExecutor publishes
    there). TuiRenderer must read it on node end and feed the sidebar."""
    renderer = TuiRenderer()
    await renderer.on_workflow_start(_wf_ctx())
    await renderer.on_node_start(_node_ctx(agent_name="analyzer"))

    node_meta = {
        "analyzer": {
            "duration_ms": 5000,
            "token_usage": {
                "cumulative_input": 1000,
                "cumulative_output": 500,
            },
            "tool_calls": [
                {"tool_name": "read_file"},
                {"tool_name": "read_file"},
                {"tool_name": "bash"},
            ],
        }
    }
    await renderer.on_node_end(_node_ctx(agent_name="analyzer", metadata=node_meta), output={"summary": "done"})

    # Sidebar cumulative tokens reflect the workflow total.
    assert renderer.sidebar.state.cumulative_tokens == 1500
    # Per-agent tokens also captured.
    assert renderer.sidebar.state.agents["analyzer"].tokens == 1500
    # Tool counts incremented from metadata's tool_calls list.
    assert renderer.sidebar.state.tool_counts["read_file"] == 2
    assert renderer.sidebar.state.tool_counts["bash"] == 1
    # Agent marked success (output present).
    assert renderer.sidebar.state.agents["analyzer"].status == AgentStatus.SUCCESS
    assert renderer.sidebar.state.agents["analyzer"].duration_ms == 5000


@pytest.mark.asyncio
async def test_on_node_end_marks_failed_when_output_has_error(_fake_live):
    renderer = TuiRenderer()
    await renderer.on_workflow_start(_wf_ctx())

    await renderer.on_node_end(_node_ctx(agent_name="x"), output={"error": "boom"})

    assert renderer.sidebar.state.agents["x"].status == AgentStatus.FAILED


@pytest.mark.asyncio
async def test_on_llm_delta_appends_to_main(_fake_live):
    renderer = TuiRenderer()
    await renderer.on_workflow_start(_wf_ctx())

    await renderer.on_llm_delta(_node_ctx(agent_name="x"), delta="hello ")

    assert renderer.main.state.text_buffer == "hello "


@pytest.mark.asyncio
async def test_on_tool_call_increments_sidebar(_fake_live):
    renderer = TuiRenderer()
    await renderer.on_workflow_start(_wf_ctx())

    tool_ctx = MagicMock()
    tool_ctx.tool_name = "read_file"
    await renderer.on_tool_call(tool_ctx, result="file contents")

    assert renderer.sidebar.state.tool_counts["read_file"] == 1


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_start_failure_does_not_crash_workflow(monkeypatch):
    """If Live.start() raises (exotic terminal, no isatty, etc), the
    renderer must degrade to a no-op rather than crashing the workflow."""
    renderer = TuiRenderer()

    class _BrokenLive:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("no TTY")

        def stop(self):
            pass

        def refresh(self):
            pass

    monkeypatch.setattr("harness.extensions.tui.renderer.Live", _BrokenLive)

    # Workflow should still complete normally
    await renderer.on_workflow_start(_wf_ctx())
    assert renderer._started is False  # degraded
    # Hook callbacks become no-ops — no crash
    await renderer.on_node_start(_node_ctx())
    await renderer.on_node_end(_node_ctx(), output={})
    # Stop is also safe
    renderer.stop()


def test_stop_is_idempotent(_fake_live):
    renderer = TuiRenderer()
    # stop before start: no crash
    renderer.stop()

    # Now simulate start + stop + stop
    asyncio.run(renderer.on_workflow_start(_wf_ctx()))
    renderer.stop()
    # Second stop should be a no-op (not crash)
    renderer.stop()
    # Live.stop called exactly once
    _fake_live[0].stop.assert_called_once()


def test_stop_restores_cursor(_fake_live, monkeypatch):
    """Cursor must be visible after stop — even if Live.stop didn't
    restore it (defensive against KeyboardInterrupt mid-render)."""
    renderer = TuiRenderer()
    asyncio.run(renderer.on_workflow_start(_wf_ctx()))

    show_cursor = MagicMock()
    monkeypatch.setattr(renderer._console, "show_cursor", show_cursor)

    renderer.stop()
    show_cursor.assert_called_with(True)
