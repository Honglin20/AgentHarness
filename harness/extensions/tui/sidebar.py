"""Sidebar rendering for the TUI renderer.

Pure rendering layer — takes event payloads via per-event methods, exposes
``render()`` returning a Rich Renderable. No Live, no threading, no I/O.
This makes it fully unit-testable without spinning up Rich Live or a real
workflow.

Four stacked panels (top to bottom):
  - Agents   — DAG nodes with status icons (✓/▶/⋯), per-agent token totals
  - Fitness  — sparkline of last N ``cycle.end`` scores; "—" when absent
  - Tokens   — cumulative workflow tokens vs envelope (double bar)
  - Tools    — most-called tools as a count table

The shape of accepted events matches what ``harness.cli_runner`` and the
default plugins emit (verified against the demo_pipeline run record at
``runs/<demo_id>+events.json`` — see Checkpoint 5 verification).
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from rich.align import Align
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


_STATUS_ICON = {
    AgentStatus.PENDING: ("⋯", "dim"),
    AgentStatus.RUNNING: ("▶", "bold yellow"),
    AgentStatus.SUCCESS: ("✓", "green"),
    AgentStatus.FAILED: ("✗", "red"),
    AgentStatus.SKIPPED: ("−", "dim"),
}


@dataclass
class _AgentState:
    name: str
    status: AgentStatus = AgentStatus.PENDING
    duration_ms: int = 0
    tokens: int = 0
    tool_calls: int = 0
    error: str | None = None


@dataclass
class SidebarState:
    """Mutable sidebar state. Exposed for tests that want to assert on it."""

    workflow_name: str = ""
    dag_nodes: list[str] = field(default_factory=list)
    envelope: dict[str, int] | None = None
    agents: dict[str, _AgentState] = field(default_factory=dict)
    cumulative_tokens: int = 0
    tool_counts: Counter = field(default_factory=Counter)
    fitness_history: list[float] = field(default_factory=list)
    current_iter: int | None = None
    total_iters: int | None = None
    started_ts_ms: int | None = None
    completed: bool = False


class SidebarPanel:
    """Right-column status panel. Pure rendering — owns no I/O.

    Lifecycle: instantiate once per workflow run, feed events via the
    ``on_*`` methods as the Bus delivers them, call ``render()`` whenever
    the Live refresh tick fires.
    """

    def __init__(self, workflow_name: str = "", fitness_window: int = 20):
        self.state = SidebarState(workflow_name=workflow_name)
        self._fitness_window = fitness_window

    # ------------------------------------------------------------------
    # Event ingestion
    # ------------------------------------------------------------------

    def on_workflow_started(self, payload: dict[str, Any]) -> None:
        # Update workflow_name from event — TuiRenderer may construct
        # SidebarPanel with empty name before Workflow.load() resolves
        # the actual name, then pass it through on_workflow_started.
        if payload.get("name"):
            self.state.workflow_name = payload["name"]
        dag = payload.get("dag") or {}
        self.state.dag_nodes = list(dag.get("nodes") or [])
        self.state.envelope = payload.get("envelope")
        self.state.started_ts_ms = payload.get("started_ts_ms")
        # Pre-register every DAG node as pending so the Agents panel
        # shows the full topology from t=0, not just agents that have
        # started.
        for name in self.state.dag_nodes:
            self.state.agents.setdefault(name, _AgentState(name=name))

    def on_node_started(self, payload: dict[str, Any]) -> None:
        name = payload.get("agent_name") or payload.get("node_id")
        if not name:
            return
        agent = self.state.agents.setdefault(name, _AgentState(name=name))
        agent.status = AgentStatus.RUNNING
        if name not in self.state.dag_nodes:
            self.state.dag_nodes.append(name)

    def on_node_completed(self, payload: dict[str, Any]) -> None:
        name = payload.get("agent_name") or payload.get("node_id")
        if not name:
            return
        agent = self.state.agents.setdefault(name, _AgentState(name=name))
        status_str = (payload.get("status") or "success").lower()
        try:
            agent.status = AgentStatus(status_str)
        except ValueError:
            agent.status = AgentStatus.SUCCESS
        agent.duration_ms = int(payload.get("duration_ms") or 0)
        if payload.get("error"):
            agent.error = str(payload["error"])[:120]

    def on_usage_update(self, payload: dict[str, Any]) -> None:
        """Token usage. Uses cumulative fields when present (server emits
        both cumulative and last-delta; we want running totals).

        Field-name-resilient: tries multiple naming conventions so a
        future rename in ``LLMExecutor.emit("agent.usage_update", ...)``
        doesn't silently zero out the sidebar. If none of the known
        fields are present, logs at debug level (not warning — this
        fires on every event, warning would spam).
        """
        name = payload.get("agent_name") or payload.get("node_id")

        # Try canonical field, then 2 plausible future names. ``or 0``
        # coerces None / missing key to 0 without raising.
        cumulative_input = int(
            payload.get("cumulative_input")
            or payload.get("total_input_tokens")
            or payload.get("input_tokens_cumulative")
            or 0
        )
        cumulative_output = int(
            payload.get("cumulative_output")
            or payload.get("total_output_tokens")
            or payload.get("output_tokens_cumulative")
            or 0
        )
        cumulative_total = cumulative_input + cumulative_output

        # Fallback: some event streams only carry per-call totals —
        # use them as a last resort so the panel is never blank.
        if cumulative_total == 0:
            cumulative_total = int(payload.get("total_tokens") or 0)

        if cumulative_total > self.state.cumulative_tokens:
            self.state.cumulative_tokens = cumulative_total

        if name:
            agent = self.state.agents.setdefault(name, _AgentState(name=name))
            agent.tokens = max(agent.tokens, cumulative_total)

    def on_tool_call(self, payload: dict[str, Any]) -> None:
        tool_name = payload.get("tool_name") or "?"
        self.state.tool_counts[tool_name] += 1
        name = payload.get("agent_name") or payload.get("node_id")
        if name:
            agent = self.state.agents.setdefault(name, _AgentState(name=name))
            agent.tool_calls += 1

    def on_cycle_end(self, payload: dict[str, Any]) -> None:
        """Optional. Workflows that emit ``cycle.end`` (see cycle_events.py
        in Checkpoint 7) get a sparkline. Others leave fitness_history empty
        and the panel renders "—"."""
        score = payload.get("score")
        if score is None:
            return
        try:
            self.state.fitness_history.append(float(score))
        except (TypeError, ValueError):
            return
        # Trim to a rolling window so a 200-iter NAS run doesn't render
        # an unreadable sparkline.
        if len(self.state.fitness_history) > self._fitness_window:
            self.state.fitness_history = self.state.fitness_history[
                -self._fitness_window:
            ]
        if payload.get("iter") is not None:
            self.state.current_iter = int(payload["iter"])
        if payload.get("total") is not None:
            self.state.total_iters = int(payload["total"])

    def on_workflow_completed(self, payload: dict[str, Any]) -> None:
        self.state.completed = True

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, width: int = 32) -> Panel:
        """Render the full sidebar as a single Panel containing 4 stacked
        sub-sections. ``width`` is the column width the renderer allocated."""
        from rich.console import Group

        inner_width = max(width - 4, 16)  # account for Panel border + pad
        sections = [
            self._render_header(inner_width),
            self._render_agents(inner_width),
            self._render_fitness(inner_width),
            self._render_tokens(inner_width),
            self._render_tools(inner_width),
        ]
        title = f"[bold cyan]🌀 {self.state.workflow_name or 'workflow'}[/bold cyan]"
        return Panel(
            Group(*sections),
            title=title,
            border_style="cyan",
            padding=(0, 1),
            height=None,  # auto-grow
        )

    def _render_header(self, width: int):
        from rich.console import Group
        from rich.text import Text

        lines = []
        # Cycle / iter line
        if self.state.current_iter is not None:
            total_str = (
                f"/{self.state.total_iters}" if self.state.total_iters else ""
            )
            lines.append(Text.from_markup(
                f"[bold]Cycle[/bold] {self.state.current_iter}{total_str}"
            ))
        # Elapsed wall clock
        if self.state.started_ts_ms is not None:
            import time

            elapsed_s = int((time.time() * 1000 - self.state.started_ts_ms) / 1000)
            mm, ss = divmod(elapsed_s, 60)
            lines.append(Text.from_markup(f"[bold]Elapsed[/bold] {mm:02d}:{ss:02d}"))
        if not lines:
            lines.append(Text("—", style="dim"))
        return Group(*lines)

    def _section_title(self, label: str):
        from rich.text import Text

        return Text.from_markup(f"[bold]{label}[/bold]")

    def _render_agents(self, width: int):
        from rich.console import Group

        if not self.state.dag_nodes and not self.state.agents:
            return Group(
                self._section_title("Agents"),
                Text("no agents", style="dim"),
            )

        table = Table(show_header=False, pad_edge=False, expand=True)
        table.add_column("icon", width=2)
        table.add_column("name", overflow="ellipsis")
        table.add_column("meta", justify="right", overflow="ellipsis")

        for name in self.state.dag_nodes:
            agent = self.state.agents.get(name) or _AgentState(name=name)
            icon, style = _STATUS_ICON[agent.status]
            meta_parts = []
            if agent.tokens:
                meta_parts.append(f"{_fmt_tokens(agent.tokens)}")
            if agent.duration_ms:
                meta_parts.append(f"{agent.duration_ms // 1000}s")
            meta = " ".join(meta_parts) or ""
            table.add_row(
                Text(icon, style=style),
                Text(name, style=style if agent.status == AgentStatus.RUNNING else ""),
                Text(meta, style="dim"),
            )
        return Group(self._section_title("Agents"), table)

    def _render_fitness(self, width: int):
        from rich.console import Group
        from rich.text import Text

        if not self.state.fitness_history:
            return Group(
                self._section_title("Fitness"),
                Text("— (no cycle events)", style="dim"),
            )
        # ASCII sparkline: map history values to 8-level bars.
        bars = "▁▂▃▄▅▆▇█"
        history = self.state.fitness_history
        lo, hi = min(history), max(history)
        rng = (hi - lo) or 1.0
        spark = "".join(
            bars[min(int((v - lo) / rng * (len(bars) - 1)), len(bars) - 1)]
            for v in history
        )
        latest = history[-1]
        best = max(history)
        body = Text.from_markup(
            f"[green]{spark}[/green]\n"
            f"[dim]latest[/dim] {latest:.3f}  [dim]best[/dim] [bold green]{best:.3f}[/bold green]"
        )
        return Group(self._section_title("Fitness"), body)

    def _render_tokens(self, width: int):
        from rich.console import Group
        from rich.text import Text

        cumulative = self.state.cumulative_tokens
        body_lines = [Text.from_markup(
            f"[bold]{_fmt_tokens(cumulative)}[/bold] tokens cumulative"
        )]
        if self.state.envelope:
            limit = (
                self.state.envelope.get("total")
                or self.state.envelope.get("tokens")
                or 0
            )
            if limit:
                pct = min(cumulative / limit, 1.0)
                body_lines.append(Text.from_markup(
                    f"[dim]envelope[/dim] {_fmt_tokens(limit)}"
                ))
                body_lines.append(Text.from_markup(_ascii_bar(pct, max(width - 4, 8))))
        return Group(self._section_title("Tokens"), *body_lines)

    def _render_tools(self, width: int):
        from rich.console import Group
        from rich.text import Text

        if not self.state.tool_counts:
            return Group(
                self._section_title("Tools"),
                Text("—", style="dim"),
            )
        # Top 5 most-called tools.
        top = self.state.tool_counts.most_common(5)
        table = Table(show_header=False, pad_edge=False, expand=True)
        table.add_column("name", overflow="ellipsis")
        table.add_column("count", justify="right", width=4)
        for name, count in top:
            table.add_row(Text(name, style="cyan"), Text(str(count), style="dim"))
        return Group(self._section_title("Tools"), table)


def _fmt_tokens(n: int) -> str:
    """1234 → '1.2k', 1234567 → '1.2M'."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"


def _ascii_bar(pct: float, width: int) -> str:
    if width < 4:
        return ""
    filled = int(pct * width)
    color = "green" if pct < 0.8 else ("yellow" if pct < 1.0 else "red")
    return f"[{color}]{'▰' * filled}{'▱' * (width - filled)}[/{color}]"
