"""TuiRenderer — Rich Live main loop wiring sidebar + main_panel.

This is the glue between the BaseHook lifecycle (driven by the engine)
and the pure-rendering SidebarPanel / MainPanel. It owns:

  - A ``rich.live.Live`` instance started on ``on_workflow_start`` and
    stopped on ``on_workflow_end`` (or finally on exception).
  - A ``rich.layout.Layout`` that splits the terminal into a 3:1 main /
    sidebar row.
  - A reference to the ``StdinCoordinator`` so ask_user can pause Live
    around ``input()`` (see Checkpoint 2's coordinator.py).

Refresh strategy
----------------
Live runs at ``refresh_per_second=4`` by default. Each hook callback
mutates panel state and calls ``Live.refresh()`` — Rich internally
throttles to the configured rate, so high-frequency events like
``on_llm_delta`` don't pin the CPU. The sidebar's elapsed-time counter
relies on this periodic refresh to tick even when no events arrive.

Robustness
----------
- ``stop()`` is idempotent and exception-tolerant: it can be called
  from a finally block after a partial start, or after the Live was
  already stopped by an upstream pause/resume cycle.
- ``stop()`` always restores the cursor (``console.show_cursor(True)``)
  so a KeyboardInterrupt mid-render doesn't leave the terminal in a
  hide-cursor state.
- Hook callbacks are no-ops when ``_live is None`` so a workflow that
  fails during setup doesn't crash the renderer.

Token usage caveat
------------------
The hook lifecycle delivers node start/end and llm deltas, but NOT
per-request token usage updates (those are emitted via ``bus.emit``
from LLMExecutor, not as hook callbacks). For now the sidebar shows
token counts on node completion (read from ``ctx.metadata``). A future
enhancement can wire TuiRenderer as a bus subscriber to get streaming
token updates.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from harness.extensions.base import (
    AgentConfig,
    BaseHook,
    NodeCtx,
    ToolCtx,
    WorkflowCtx,
)
from harness.extensions.tui.coordinator import StdinCoordinator
from harness.extensions.tui.main_panel import MainPanel
from harness.extensions.tui.sidebar import SidebarPanel

logger = logging.getLogger(__name__)


class TuiRenderer(BaseHook):
    """Live-rendering BaseHook. Drop-in replacement for ConsoleOutput
    when the CLI is in TUI mode."""

    name = "tui-renderer"

    def __init__(
        self,
        workflow_name: str = "",
        refresh_per_second: int = 4,
        main_ratio: int = 3,
        sidebar_ratio: int = 1,
    ):
        self._sidebar = SidebarPanel(workflow_name=workflow_name)
        self._main = MainPanel()
        self._refresh_per_second = refresh_per_second
        self._main_ratio = main_ratio
        self._sidebar_ratio = sidebar_ratio
        self._live: Optional[Live] = None
        self._layout: Optional[Layout] = None
        self._console = Console()
        self._coord: Optional[StdinCoordinator] = None
        self._started = False

    # ------------------------------------------------------------------
    # Wiring (called by cli_runner / cmd_run)
    # ------------------------------------------------------------------

    def attach_coordinator(self, coord: StdinCoordinator) -> None:
        """Bind the StdinCoordinator so ask_user can pause/resume Live.

        Called by ``harness run`` (cmd_run) BEFORE workflow execution.
        When Live starts in ``on_workflow_start``, we forward the Live
        instance to the coordinator via ``attach_live`` so the ask_user
        pause/resume actually controls this renderer.
        """
        self._coord = coord

    @property
    def sidebar(self) -> SidebarPanel:
        """Exposed for tests + future bus-subscriber enhancements."""
        return self._sidebar

    @property
    def main(self) -> MainPanel:
        return self._main

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_row(
            Layout(name="main", ratio=self._main_ratio),
            Layout(name="sidebar", ratio=self._sidebar_ratio),
        )
        return layout

    def _refresh(self) -> None:
        """Re-render both panels into the layout + nudge Live.

        Safe to call when Live isn't started yet (no-op). Rich's Live
        throttles calls to ``refresh()`` to ``refresh_per_second``, so
        invoking this on every hook callback does NOT pin CPU even when
        on_llm_delta fires 50× per second.
        """
        if self._live is None or self._layout is None:
            return
        # Size hints: the layout's actual column widths aren't known
        # until after Live measures them, so we pass generous defaults
        # and let Rich wrap/truncate. Main panel needs a height hint so
        # the ring buffer shows enough lines.
        self._layout["main"].update(
            self._main.render(width=80, height=30)
        )
        self._layout["sidebar"].update(self._sidebar.render(width=36))
        try:
            self._live.refresh()
        except Exception:
            # Live can raise if called after stop() or during shutdown.
            # TuiRenderer must never break the workflow over a render hiccup.
            logger.debug("TuiRenderer live.refresh() failed", exc_info=True)

    # ------------------------------------------------------------------
    # BaseHook lifecycle
    # ------------------------------------------------------------------

    async def on_workflow_start(self, ctx: WorkflowCtx) -> None:
        # Seed sidebar with the DAG topology and envelope from the builder.
        # ctx.inputs + ctx.workflow_name give us the metadata sidebar needs.
        dag_payload: dict[str, Any] = {"nodes": [], "edges": []}
        envelope = None
        try:
            # Walk back to the workflow to grab agents + envelope. ctx
            # itself doesn't carry these — they live on the Workflow
            # object the engine is running. We use a getattr chain to
            # avoid a hard import dependency on Workflow here.
            wf = getattr(ctx, "_workflow_ref", None)
            if wf is not None:
                from harness.compiler.dag_builder import build_dag

                nodes = build_dag(wf.agents)
                edges = [[dep, a.name] for a in wf.agents for dep in (a.after or [])]
                dag_payload = {"nodes": nodes, "edges": edges}
                envelope = getattr(wf, "envelope", None)
        except Exception:
            logger.debug("Could not read workflow DAG for sidebar", exc_info=True)

        import time

        self._sidebar.on_workflow_started({
            "name": ctx.workflow_name,
            "dag": dag_payload,
            "envelope": envelope,
            "started_ts_ms": int(time.time() * 1000),
        })

        # Build + start Live. screen=False keeps scrollback usable
        # (full-screen mode would clear the terminal on exit).
        self._layout = self._build_layout()
        self._live = Live(
            self._layout,
            console=self._console,
            refresh_per_second=self._refresh_per_second,
            transient=False,
            screen=False,
        )
        try:
            self._live.start()
            self._started = True
        except Exception:
            # Live may fail to start on exotic terminals (no isatty, etc).
            # Mark as not-started so hook callbacks no-op gracefully —
            # the workflow itself is unaffected.
            logger.warning("TuiRenderer Live.start() failed — falling back to no-op", exc_info=True)
            self._live = None
            return

        # Forward the Live instance to the StdinCoordinator so ask_user's
        # pause/resume actually controls this renderer.
        if self._coord is not None:
            self._coord.attach_live(self._live)

        self._refresh()

    async def on_workflow_end(self, ctx: WorkflowCtx, result: dict[str, Any]) -> None:
        # Emit a completion line so the final render shows the summary.
        outputs = {}
        errors = {}
        if isinstance(result, dict):
            outputs = result.get("outputs") or {}
            errors = result.get("errors") or {}
        status = "failed" if errors else "completed"
        self._sidebar.on_workflow_completed({"status": status, "outputs": outputs})
        self._main.on_workflow_completed({"outputs": outputs, "errors": errors})
        self._refresh()
        # Stop Live after the final refresh so the user sees the
        # completed state frozen on screen.
        self.stop()

    async def on_node_start(self, ctx: NodeCtx) -> None:
        payload = {
            "agent_name": ctx.agent_name,
            "node_id": ctx.node_id,
        }
        self._sidebar.on_node_started(payload)
        self._main.on_node_started(payload)
        self._refresh()

    async def on_node_end(self, ctx: NodeCtx, output: Any) -> None:
        # Read token usage from ctx.metadata (where LLMExecutor publishes
        # per-node totals). Fallback to 0 if absent.
        node_meta = ctx.metadata.get(ctx.agent_name, {}) if ctx.metadata else {}
        if isinstance(node_meta, dict):
            token_usage = node_meta.get("token_usage") or {}
            duration_ms = int(node_meta.get("duration_ms") or 0)
            tool_calls = node_meta.get("tool_calls") or []
        else:
            token_usage, duration_ms, tool_calls = {}, 0, []

        # Synthesize an agent.usage_update from the per-node totals so
        # the sidebar's cumulative counter advances on node completion.
        if isinstance(token_usage, dict):
            cumulative_input = int(token_usage.get("cumulative_input") or token_usage.get("input_tokens") or 0)
            cumulative_output = int(token_usage.get("cumulative_output") or token_usage.get("output_tokens") or 0)
            if cumulative_input or cumulative_output:
                self._sidebar.on_usage_update({
                    "agent_name": ctx.agent_name,
                    "cumulative_input": cumulative_input,
                    "cumulative_output": cumulative_output,
                    "total_tokens": cumulative_input + cumulative_output,
                })

        # Determine node status from presence in workflow errors.
        status = "success"
        wf_errors = (
            ctx.workflow.metadata.get("_errors", {})
            if hasattr(ctx.workflow, "metadata")
            else {}
        )
        # ctx.workflow.metadata is per-extension scratchpad; the global
        # errors live on WorkflowResult, not WorkflowCtx. Use a simpler
        # heuristic: if output is None or an error-shaped dict, mark failed.
        if output is None:
            status = "skipped"
        elif isinstance(output, dict) and output.get("error"):
            status = "failed"

        self._sidebar.on_node_completed({
            "agent_name": ctx.agent_name,
            "status": status,
            "duration_ms": duration_ms,
        })
        self._main.on_node_completed({
            "agent_name": ctx.agent_name,
            "status": status,
            "duration_ms": duration_ms,
        })
        # Record tool calls counted during this node.
        for tc in tool_calls:
            tool_name = tc.get("tool_name") if isinstance(tc, dict) else str(tc)
            if tool_name:
                self._sidebar.on_tool_call({"tool_name": tool_name})
        self._refresh()

    async def on_llm_delta(self, ctx: NodeCtx, delta: str) -> None:
        # Engine emits deltas for both thinking + final text via the same
        # callback. The dim/italic styling on thinking is decided in
        # MainPanel based on which buffer is active — for now we route
        # all deltas to the text buffer; a richer split awaits
        # bus-subscriber integration for agent.thinking_delta.
        if delta:
            self._main.on_text_delta({"text": delta})
            # Don't refresh on every delta — Live's 4Hz throttle handles
            # the timing. Just mark dirty by mutating state; the next
            # hook callback OR Live's tick will refresh.
            # But we DO want prompt updates, so call refresh and let Rich
            # throttle.
            self._refresh()

    async def on_tool_call(self, ctx: ToolCtx, result: Any) -> None:
        tool_name = getattr(ctx, "tool_name", "?")
        self._sidebar.on_tool_call({"tool_name": tool_name})
        self._main.on_tool_call({"tool_name": tool_name, "tool_args": {}})
        result_str = str(result)
        if len(result_str) > 120:
            result_str = result_str[:117] + "..."
        self._main.on_tool_result({"tool_name": tool_name, "result": result_str})
        self._refresh()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop Live and restore terminal state. Idempotent.

        Called from ``on_workflow_end`` on success AND from the cmd_run
        ``finally`` block on failure. Must handle:
          - Live already stopped (double-call)
          - Live not yet started (failure during setup)
          - Cursor hidden by a previous Live cycle
        """
        if not self._started:
            return
        self._started = False
        if self._coord is not None:
            try:
                self._coord.detach_live()
            except Exception:
                pass
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                logger.debug("TuiRenderer Live.stop() failed", exc_info=True)
            finally:
                self._live = None
        # Always restore the cursor — Live hides it on start, and an
        # exception path can skip the implicit restore on stop().
        try:
            self._console.show_cursor(True)
        except Exception:
            pass
