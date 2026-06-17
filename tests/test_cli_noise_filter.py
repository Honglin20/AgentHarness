"""Tests for the mcp + asyncio shutdown noise filter installed in cli.py.

Locks the contract that the filter:
  1. Drops "Event loop is closed" + "cancel scope" messages (mcp/asyncio
     shutdown cosmetic noise).
  2. Forwards everything else to the original hook (real bugs surface).
  3. Doesn't crash on weirdly-shaped err args.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness import cli as cli_mod


class _CapturingHook:
    """Stand-in for sys.unraisablehook that records every call."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, err):
        self.calls.append(err)


@pytest.fixture
def captured_hook(monkeypatch):
    """Replace _orig_unraisablehook with a capture so we can assert the
    filter forwarded non-noise calls."""
    capture = _CapturingHook()
    monkeypatch.setattr(cli_mod, "_orig_unraisablehook", capture)
    return capture


def _err(msg):
    return SimpleNamespace(err_msg=msg, object=None, expected_type=None)


# ---------------------------------------------------------------------------
# Noise patterns are filtered
# ---------------------------------------------------------------------------


def test_event_loop_closed_message_filtered(captured_hook):
    cli_mod._filtered_unraisablehook(_err("RuntimeError: Event loop is closed"))
    assert captured_hook.calls == []  # not forwarded


def test_cancel_scope_message_filtered(captured_hook):
    cli_mod._filtered_unraisablehook(
        _err("RuntimeError: Attempted to exit a cancel scope that isn't the current")
    )
    assert captured_hook.calls == []


def test_partial_match_still_filtered(captured_hook):
    """Substring match, not exact — protects against minor wording
    variations across anyio versions."""
    cli_mod._filtered_unraisablehook(
        _err("something something Event loop is closed during cleanup")
    )
    assert captured_hook.calls == []


# ---------------------------------------------------------------------------
# Real errors pass through
# ---------------------------------------------------------------------------


def test_other_errors_forwarded(captured_hook):
    err = _err("ValueError: actual problem")
    cli_mod._filtered_unraisablehook(err)
    assert captured_hook.calls == [err]


def test_empty_message_forwarded(captured_hook):
    """Defensive: empty err_msg shouldn't crash the filter (would let
    every other error slip through the noise check via exception)."""
    err = _err("")
    cli_mod._filtered_unraisablehook(err)
    assert captured_hook.calls == [err]


def test_none_message_forwarded(captured_hook):
    """Defensive: err_msg may be None on some Python versions."""
    err = SimpleNamespace(err_msg=None, object=None, expected_type=None)
    cli_mod._filtered_unraisablehook(err)
    assert captured_hook.calls == [err]


# ---------------------------------------------------------------------------
# Hook installation
# ---------------------------------------------------------------------------


def test_filter_installed_on_module_import():
    """``sys.unraisablehook`` should be set to the filter after cli.py
    imports. Locks that the install-on-import logic isn't accidentally
    removed in a refactor."""
    import sys
    assert sys.unraisablehook is cli_mod._filtered_unraisablehook
