"""Tests for compact.py — the TTY router that picks TuiRenderer or
ConsoleOutput fallback.

Critical contract: piped stdout (CI logs, subprocess capture) must NOT
get a TuiRenderer, otherwise Rich Live dumps ANSI cursor-control codes
into the captured file and the user sees nothing on the actual terminal.
"""

from __future__ import annotations

import sys

import pytest

from harness.extensions.tui.compact import is_tty, select_output


def test_is_tty_returns_false_when_stdout_not_tty(monkeypatch):
    """Piped stdout → False, even if stdin is a TTY."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert is_tty() is False


def test_is_tty_returns_false_when_stdin_not_tty(monkeypatch):
    """Piped stdin → False, even if stdout is a TTY."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert is_tty() is False


def test_is_tty_returns_true_only_when_both_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert is_tty() is True


def test_is_tty_handles_missing_isatty_attr(monkeypatch):
    """stdin/stdout replaced with non-file objects (pytest capture, IDE
    redirected streams) must not crash — return False so the run still
    completes via ConsoleOutput."""
    class _NoIsatty:
        pass

    monkeypatch.setattr(sys, "stdin", _NoIsatty())
    monkeypatch.setattr(sys, "stdout", _NoIsatty())
    assert is_tty() is False


def test_select_output_returns_none_when_forced_no_tty(monkeypatch):
    """--no-tui always picks ConsoleOutput path even on a real TTY."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert select_output(force_no_tui=True) is None


def test_select_output_returns_none_when_not_tty(monkeypatch):
    """Non-TTY → None → cli_runner uses ConsoleOutput fallback."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert select_output(force_no_tui=False) is None


def test_select_output_returns_tui_renderer_when_tty(monkeypatch):
    """TTY + no force → TuiRenderer instance."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    from harness.extensions.tui.renderer import TuiRenderer

    result = select_output(force_no_tui=False, workflow_name="demo")
    assert isinstance(result, TuiRenderer)
    assert result.sidebar.state.workflow_name == "demo"


def test_select_output_passes_workflow_name_to_renderer(monkeypatch):
    """Workflow name flows through so sidebar can render the title from
    the first frame, before on_workflow_start fires."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    result = select_output(force_no_tui=False, workflow_name="nas")
    assert result is not None
    assert result.sidebar.state.workflow_name == "nas"
