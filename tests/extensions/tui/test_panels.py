"""Unit tests for SidebarPanel and MainPanel.

Pure-rendering tests — no Live, no workflow. Feed events via the ``on_*``
methods, assert on ``state`` and on ``render()`` output.

For render() assertions, capture to a string Console (``Console(file=io.StringIO())``)
so we can grep the rendered text without spawning a real terminal.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from harness.extensions.tui.main_panel import MainPanel
from harness.extensions.tui.sidebar import AgentStatus, SidebarPanel


def _render_to_str(panel, width: int = 80) -> str:
    """Render a panel and capture as plain text."""
    buf = io.StringIO()
    console = Console(file=buf, width=width, force_terminal=False, color_system=None)
    renderable = panel.render(width=width) if hasattr(panel, "render") and panel.__class__.__name__ == "SidebarPanel" else panel.render(width=width, height=40)
    console.print(renderable)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# SidebarPanel
# ---------------------------------------------------------------------------


class TestSidebarAgents:
    def test_pending_state_when_workflow_started(self):
        sb = SidebarPanel(workflow_name="demo")
        sb.on_workflow_started({
            "dag": {"nodes": ["analyzer", "planner", "reviewer"]},
            "envelope": {"total": 100000},
        })
        assert sb.state.dag_nodes == ["analyzer", "planner", "reviewer"]
        assert sb.state.agents["analyzer"].status == AgentStatus.PENDING
        assert sb.state.agents["planner"].status == AgentStatus.PENDING

    def test_running_then_success_lifecycle(self):
        sb = SidebarPanel()
        sb.on_workflow_started({"dag": {"nodes": ["a"]}})
        sb.on_node_started({"agent_name": "a"})
        assert sb.state.agents["a"].status == AgentStatus.RUNNING
        sb.on_node_completed({"agent_name": "a", "status": "success", "duration_ms": 1500})
        assert sb.state.agents["a"].status == AgentStatus.SUCCESS
        assert sb.state.agents["a"].duration_ms == 1500

    def test_failed_status_recorded(self):
        sb = SidebarPanel()
        sb.on_node_started({"agent_name": "x"})
        sb.on_node_completed({"agent_name": "x", "status": "failed", "error": "boom"})
        assert sb.state.agents["x"].status == AgentStatus.FAILED
        assert "boom" in (sb.state.agents["x"].error or "")

    def test_dag_nodes_in_render_order(self):
        """Agents panel must list nodes in DAG order, not insertion order."""
        sb = SidebarPanel()
        sb.on_workflow_started({"dag": {"nodes": ["c", "a", "b"]}})
        sb.on_node_started({"agent_name": "a"})  # would reorder in dict
        sb.on_node_started({"agent_name": "c"})
        out = _render_to_str(sb, width=40)
        # c must appear before a, a before b (DAG order)
        assert out.index("c") < out.index("a")
        assert out.index("a") < out.index("b")

    def test_running_agent_marked_in_render(self):
        sb = SidebarPanel()
        sb.on_workflow_started({"dag": {"nodes": ["a", "b"]}})
        sb.on_node_started({"agent_name": "a"})
        out = _render_to_str(sb, width=40)
        assert "▶" in out  # running icon


class TestSidebarTokens:
    def test_cumulative_tokens_track_usage_update(self):
        sb = SidebarPanel()
        sb.on_usage_update({
            "agent_name": "a",
            "cumulative_input": 1000,
            "cumulative_output": 500,
        })
        assert sb.state.cumulative_tokens == 1500
        sb.on_usage_update({
            "agent_name": "a",
            "cumulative_input": 2000,
            "cumulative_output": 800,
        })
        # 2800 > 1500 → takes the max (cumulative is monotonic per agent)
        assert sb.state.cumulative_tokens == 2800

    def test_envelope_bar_rendered(self):
        sb = SidebarPanel()
        sb.on_workflow_started({
            "dag": {"nodes": []},
            "envelope": {"total": 10000},
        })
        sb.on_usage_update({
            "agent_name": "x",
            "cumulative_input": 5000,
            "cumulative_output": 0,
        })
        out = _render_to_str(sb, width=40)
        assert "5.0k" in out  # tokens formatted
        assert "▰" in out and "▱" in out  # ascii bar present

    def test_no_usage_renders_zero(self):
        sb = SidebarPanel()
        sb.on_workflow_started({"dag": {"nodes": []}})
        out = _render_to_str(sb, width=40)
        assert "0" in out  # zero tokens

    def test_usage_update_resilient_to_field_rename(self):
        """If LLMExecutor renames cumulative_input/output to one of the
        plausible future schemas (total_input_tokens / input_tokens_cumulative),
        the sidebar must keep working instead of silently zeroing out.
        Locks the resilience contract added after Cp7."""
        sb = SidebarPanel()

        # Future name pattern 1: total_input_tokens / total_output_tokens
        sb.on_usage_update({
            "agent_name": "x",
            "total_input_tokens": 3000,
            "total_output_tokens": 1500,
        })
        assert sb.state.cumulative_tokens == 4500

        # Future name pattern 2: input_tokens_cumulative / output_tokens_cumulative
        sb2 = SidebarPanel()
        sb2.on_usage_update({
            "agent_name": "y",
            "input_tokens_cumulative": 2000,
            "output_tokens_cumulative": 700,
        })
        assert sb2.state.cumulative_tokens == 2700

    def test_usage_update_falls_back_to_total_tokens(self):
        """Older event streams may only carry the per-call total_tokens
        field — sidebar must use it rather than render blank."""
        sb = SidebarPanel()
        sb.on_usage_update({
            "agent_name": "x",
            "total_tokens": 9000,
        })
        assert sb.state.cumulative_tokens == 9000

    def test_usage_update_missing_all_fields_does_not_crash(self):
        """Garbage event with no recognized token fields must not raise.
        Sidebar stays at 0; the workflow continues."""
        sb = SidebarPanel()
        sb.on_usage_update({"agent_name": "x"})  # no token fields
        assert sb.state.cumulative_tokens == 0


class TestSidebarFitness:
    def test_no_cycle_events_renders_dash(self):
        sb = SidebarPanel()
        sb.on_workflow_started({"dag": {"nodes": []}})
        out = _render_to_str(sb, width=40)
        assert "no cycle events" in out or "—" in out

    def test_cycle_end_appends_to_history(self):
        sb = SidebarPanel()
        sb.on_cycle_end({"score": 0.5, "iter": 1})
        sb.on_cycle_end({"score": 0.7, "iter": 2})
        sb.on_cycle_end({"score": 0.9, "iter": 3})
        assert sb.state.fitness_history == [0.5, 0.7, 0.9]
        assert sb.state.current_iter == 3

    def test_cycle_end_rolling_window(self):
        sb = SidebarPanel(fitness_window=3)
        for i in range(5):
            sb.on_cycle_end({"score": i * 0.1, "iter": i + 1})
        assert len(sb.state.fitness_history) == 3
        # Most recent 3 (last 3 of [0.0, 0.1, 0.2, 0.3, 0.4])
        # Float comparison — 0.1*3 produces 0.30000000000000004
        assert sb.state.fitness_history == pytest.approx([0.2, 0.3, 0.4])

    def test_cycle_end_renders_sparkline(self):
        sb = SidebarPanel()
        sb.on_workflow_started({"dag": {"nodes": []}})
        for s in [0.1, 0.4, 0.7, 0.9, 0.95]:
            sb.on_cycle_end({"score": s})
        out = _render_to_str(sb, width=40)
        # Sparkline chars are in the ▁▂▃▄▅▆▇█ family
        assert any(c in out for c in "▁▂▃▄▅▆▇█")
        assert "0.950" in out or "0.95" in out  # best score formatted

    def test_invalid_score_ignored(self):
        sb = SidebarPanel()
        sb.on_cycle_end({"score": "not-a-number"})
        assert sb.state.fitness_history == []
        sb.on_cycle_end({"score": None})
        assert sb.state.fitness_history == []


class TestSidebarTools:
    def test_tool_counts_aggregate(self):
        sb = SidebarPanel()
        sb.on_tool_call({"tool_name": "read_file"})
        sb.on_tool_call({"tool_name": "read_file"})
        sb.on_tool_call({"tool_name": "bash"})
        assert sb.state.tool_counts["read_file"] == 2
        assert sb.state.tool_counts["bash"] == 1

    def test_tool_panel_renders_top_5(self):
        sb = SidebarPanel()
        sb.on_workflow_started({"dag": {"nodes": []}})
        for _ in range(10):
            sb.on_tool_call({"tool_name": "a"})
        for _ in range(5):
            sb.on_tool_call({"tool_name": "b"})
        out = _render_to_str(sb, width=40)
        assert "a" in out and "10" in out
        assert "b" in out and "5" in out

    def test_per_agent_tool_count(self):
        sb = SidebarPanel()
        sb.on_workflow_started({"dag": {"nodes": ["x"]}})
        sb.on_tool_call({"agent_name": "x", "tool_name": "a"})
        sb.on_tool_call({"agent_name": "x", "tool_name": "b"})
        assert sb.state.agents["x"].tool_calls == 2


# ---------------------------------------------------------------------------
# MainPanel
# ---------------------------------------------------------------------------


class TestMainPanelStreaming:
    def test_text_delta_accumulates(self):
        mp = MainPanel()
        mp.on_text_delta({"text": "Hello"})
        mp.on_text_delta({"text": " world"})
        assert mp.state.text_buffer == "Hello world"

    def test_text_delta_flushes_on_newline(self):
        mp = MainPanel(flush_every_chars=1000)
        mp.on_text_delta({"text": "first line\n"})
        # Newline triggers flush → buffer empty, line appended
        assert mp.state.text_buffer == ""
        assert len(mp.state.lines) == 1

    def test_text_delta_flushes_on_char_threshold(self):
        mp = MainPanel(flush_every_chars=10)
        mp.on_text_delta({"text": "0123456789"})  # exactly 10 chars
        assert mp.state.text_buffer == ""
        assert len(mp.state.lines) == 1

    def test_thinking_delta_renders_dim(self):
        mp = MainPanel(flush_every_chars=4)
        mp.on_thinking_delta({"text": "Let me think about this"})
        out = _render_to_str(mp, width=60)
        # Dim text should appear in output (no color codes since
        # color_system=None, but the text content must be present)
        assert "Let me think" in out


class TestMainPanelNodes:
    def test_node_started_adds_section_header(self):
        mp = MainPanel()
        mp.on_node_started({"agent_name": "analyzer"})
        # First line should be a Rule (section header)
        assert len(mp.state.lines) == 1
        out = _render_to_str(mp, width=60)
        assert "analyzer" in out

    def test_node_completed_adds_status_line(self):
        mp = MainPanel()
        mp.on_node_started({"agent_name": "x"})
        mp.on_node_completed({"agent_name": "x", "status": "success", "duration_ms": 2000})
        # Section header + status line
        assert len(mp.state.lines) == 2
        out = _render_to_str(mp, width=60)
        assert "2s" in out

    def test_node_failed_uses_x_icon(self):
        mp = MainPanel()
        mp.on_node_completed({"agent_name": "x", "status": "failed"})
        out = _render_to_str(mp, width=60)
        assert "✗" in out


class TestMainPanelTools:
    def test_tool_call_renders_with_arg_preview(self):
        mp = MainPanel()
        mp.on_tool_call({"tool_name": "read_file", "tool_args": {"path": "/tmp/x"}})
        out = _render_to_str(mp, width=60)
        assert "read_file" in out
        assert "path" in out  # arg key shown

    def test_tool_result_truncated(self):
        mp = MainPanel()
        long_result = "x" * 200
        mp.on_tool_result({"tool_name": "bash", "result": long_result})
        out = _render_to_str(mp, width=80)
        # 200 chars truncated to 120 + "..."
        assert "..." in out

    def test_tool_call_no_args_no_parens(self):
        mp = MainPanel()
        mp.on_tool_call({"tool_name": "noop", "tool_args": {}})
        out = _render_to_str(mp, width=60)
        assert "noop" in out
        # No parens when args empty
        line = [l for l in out.split("\n") if "noop" in l][0]
        assert "()" not in line


class TestMainPanelBuffer:
    def test_ring_buffer_max_size(self):
        mp = MainPanel(max_lines=10)
        for i in range(20):
            mp.on_node_completed({"agent_name": f"agent_{i}", "status": "success"})
        assert len(mp.state.lines) == 10  # ring buffer bounded

    def test_flush_buffers_on_node_boundary(self):
        """Unflushed text buffer must be flushed when a new node starts
        so it doesn't bleed into the next agent's section."""
        mp = MainPanel(flush_every_chars=1000)
        mp.on_node_started({"agent_name": "a"})
        mp.on_text_delta({"text": "agent a output without newline"})
        mp.on_node_started({"agent_name": "b"})
        # Buffer flushed on b's section header
        assert mp.state.text_buffer == ""
        assert len(mp.state.lines) >= 2  # header + flushed text + new header
