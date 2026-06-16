"""Main panel — left-column scrolling log of agent activity.

Consumes the streaming events (``agent.text_delta`` / ``agent.thinking_delta``
/ ``agent.tool_call`` / ``agent.tool_result`` / node lifecycle) and renders
a chronological log. Uses a ring buffer so a 200-iter NAS run doesn't
accumulate unbounded lines in memory.

Pure rendering — no Live, no threading. ``render()`` returns a Panel
suitable for Rich Layout's main area.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text


@dataclass
class _Line:
    """One rendered log line. Either rich Text or a Renderable."""
    content: Any  # Text | Rule | Table
    agent: str | None = None


@dataclass
class MainPanelState:
    current_agent: str | None = None
    lines: deque = field(default_factory=lambda: deque(maxlen=500))
    text_buffer: str = ""  # streaming text not yet flushed
    thinking_buffer: str = ""  # streaming thinking not yet flushed


class MainPanel:
    """Left-column scrolling log."""

    def __init__(self, max_lines: int = 500, flush_every_chars: int = 80):
        self.state = MainPanelState(
            lines=deque(maxlen=max_lines),
        )
        self._flush_every = flush_every_chars

    # ------------------------------------------------------------------
    # Event ingestion
    # ------------------------------------------------------------------

    def on_node_started(self, payload: dict[str, Any]) -> None:
        self._flush_buffers()
        name = payload.get("agent_name") or payload.get("node_id") or "?"
        self.state.current_agent = name
        # Section header — visual break between agents.
        self.state.lines.append(_Line(
            content=Rule(
                title=f"[bold yellow]▶ {name}[/bold yellow]",
                style="yellow",
            ),
            agent=name,
        ))

    def on_node_completed(self, payload: dict[str, Any]) -> None:
        self._flush_buffers()
        name = payload.get("agent_name") or payload.get("node_id") or "?"
        status = (payload.get("status") or "success").lower()
        duration_ms = int(payload.get("duration_ms") or 0)
        if status == "success":
            icon, style = "✓", "green"
        elif status == "failed":
            icon, style = "✗", "red"
        else:
            icon, style = "−", "dim"
        # Compact completion line. Full agent output is already in the
        # text_delta stream above; this is just a status stamp.
        meta = f"  [dim]{duration_ms // 1000}s[/dim]" if duration_ms else ""
        self.state.lines.append(_Line(
            content=Text.from_markup(
                f"[{style}]{icon} {name}[/{style}]{meta}"
            ),
            agent=name,
        ))
        if self.state.current_agent == name:
            self.state.current_agent = None

    def on_text_delta(self, payload: dict[str, Any]) -> None:
        text = payload.get("text") or ""
        if not text:
            return
        self.state.text_buffer += text
        # Flush on newline or buffer threshold to keep memory bounded
        # while preserving streaming feel.
        if "\n" in self.state.text_buffer or len(self.state.text_buffer) >= self._flush_every:
            self._flush_text()

    def on_thinking_delta(self, payload: dict[str, Any]) -> None:
        """Reasoning trace. Rendered dim + italic to visually separate
        from the final assistant text."""
        text = payload.get("text") or ""
        if not text:
            return
        self.state.thinking_buffer += text
        if "\n" in self.state.thinking_buffer or len(self.state.thinking_buffer) >= self._flush_every:
            self._flush_thinking()

    def on_tool_call(self, payload: dict[str, Any]) -> None:
        self._flush_buffers()
        tool = payload.get("tool_name") or "?"
        args = payload.get("tool_args") or {}
        # Compact one-line preview of args — full result follows via
        # on_tool_result. Show key + first value to keep it scannable.
        arg_preview = _preview_args(args)
        self.state.lines.append(_Line(
            content=Text.from_markup(
                f"  [magenta]🔧 {tool}[/magenta]"
                + (f"[dim]({arg_preview})[/dim]" if arg_preview else "")
            ),
        ))

    def on_tool_result(self, payload: dict[str, Any]) -> None:
        tool = payload.get("tool_name") or "?"
        result = payload.get("result")
        result_str = str(result) if result is not None else ""
        # Truncate aggressively — tool results can be huge (file reads,
        # bash output). The agent already has the full result; the TUI
        # only needs a "what happened" preview.
        if len(result_str) > 120:
            result_str = result_str[:117] + "..."
        self.state.lines.append(_Line(
            content=Text.from_markup(f"    [dim]↳ {result_str}[/dim]"),
        ))

    def on_workflow_completed(self, payload: dict[str, Any]) -> None:
        self._flush_buffers()
        outputs = payload.get("outputs") or {}
        if outputs:
            self.state.lines.append(_Line(content=Rule(style="green")))
            for agent_name, out in outputs.items():
                preview = _preview_output(out)
                self.state.lines.append(_Line(
                    content=Text.from_markup(
                        f"[bold green]✓ {agent_name}[/bold green]: {preview}"
                    ),
                ))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, width: int = 80, height: int = 20) -> Panel:
        from rich.console import Console, Group

        # The deque holds the last N lines; render only the bottom
        # ``height`` so the panel behaves like a tail -f log.
        recent = list(self.state.lines)[-height:]
        renderables = [line.content for line in recent]
        # If buffers have unflushed content (e.g. mid-stream), include
        # them so the user sees the live tail.
        if self.state.thinking_buffer:
            renderables.append(Text(self.state.thinking_buffer, style="dim italic"))
        if self.state.text_buffer:
            renderables.append(Text(self.state.text_buffer))

        body = Group(*renderables) if renderables else Text("[dim]waiting for events…[/dim]")
        return Panel(
            body,
            title="[bold cyan]Agent Output[/bold cyan]",
            border_style="blue",
            padding=(0, 1),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush_buffers(self) -> None:
        self._flush_thinking()
        self._flush_text()

    def _flush_text(self) -> None:
        if not self.state.text_buffer:
            return
        text = self.state.text_buffer.rstrip()
        self.state.text_buffer = ""
        if text:
            self.state.lines.append(_Line(content=Text(text)))

    def _flush_thinking(self) -> None:
        if not self.state.thinking_buffer:
            return
        text = self.state.thinking_buffer.rstrip()
        self.state.thinking_buffer = ""
        if text:
            self.state.lines.append(_Line(content=Text(text, style="dim italic")))


def _preview_args(args: Any, max_chars: int = 60) -> str:
    """Compact arg preview: ``{op: 'create', items: [...]}`` → "op=create"."""
    if not isinstance(args, dict):
        s = str(args)
        return s[:max_chars]
    parts = []
    running = 0
    for k, v in args.items():
        if running >= max_chars:
            parts.append("…")
            break
        if isinstance(v, str):
            v_repr = v[:20] + ("…" if len(v) > 20 else "")
        elif isinstance(v, (list, dict)):
            v_repr = f"{type(v).__name__}({len(v)})"
        else:
            v_repr = repr(v)[:20]
        chunk = f"{k}={v_repr}"
        parts.append(chunk)
        running += len(chunk) + 2
    return ", ".join(parts)


def _preview_output(output: Any, max_chars: int = 120) -> str:
    """One-line preview of an agent's final output for the workflow
    completion summary."""
    if isinstance(output, dict):
        summary = output.get("summary") or output.get("result") or ""
        if summary:
            s = str(summary)
            return s[:max_chars] + ("…" if len(s) > max_chars else "")
        # No summary — show first key=value pair.
        for k, v in output.items():
            s = f"{k}={v}"
            return s[:max_chars] + ("…" if len(s) > max_chars else "")
        return "{}"
    s = str(output)
    return s[:max_chars] + ("…" if len(s) > max_chars else "")
