"""Tests for harness.tools._truncate — tool result size bounding.

Stage 3 of the token-stats fix plan: long tool returns (bash stdout,
codegraph_explore source dumps) used to enter message_history verbatim,
inflating input_tokens on every subsequent model request. Truncation
bounds that growth.
"""

from __future__ import annotations

import os

import pytest

from harness.tools._truncate import (
    _DEFAULT_LIMIT,
    _TOOL_LIMITS_EXACT,
    emit_tool_output_truncated,
    truncate_tool_result,
    truncation_context,
)


# ── truncate_tool_result: byte budgeting ───────────────────────────────

def test_short_result_unchanged():
    out, was_cut, original = truncate_tool_result("bash", "hello")
    assert out == "hello"
    assert was_cut is False
    assert original == 5


def test_non_string_result_passes_through():
    """Non-str returns (dict, None) are not safe to truncate — leave alone."""
    for val in (None, {"k": "v"}, [1, 2, 3], 42):
        out, was_cut, original = truncate_tool_result("bash", val)
        assert out is val
        assert was_cut is False
        assert original == 0


def test_bash_result_over_limit_truncated():
    """8KB+ bash output gets cut to the bash limit (8192) + notice tail."""
    big = "x" * 10_000
    out, was_cut, original = truncate_tool_result("bash", big)
    assert was_cut is True
    assert original == 10_000
    final_bytes = len(out.encode("utf-8"))
    # Final payload (body + notice) must respect the limit.
    assert final_bytes <= 8192
    # Notice must be appended.
    assert "[... truncated" in out
    assert "codegraph_node" in out  # actionable hint for getting full content


def test_codegraph_uses_lower_limit():
    """codegraph_* tools get 6KB (less than default 8KB) because their output
    is structured source dumps where the LLM often only needs the signature."""
    big = "x" * 7000
    out, was_cut, _ = truncate_tool_result("codegraph_explore", big)
    assert was_cut is True
    assert len(out.encode("utf-8")) <= 6144

    out2, was_cut2, _ = truncate_tool_result("codegraph_search", big)
    assert was_cut2 is True


def test_unknown_tool_uses_default_limit():
    """Tools not in the per-tool dict fall back to the default."""
    big = "x" * (_DEFAULT_LIMIT + 100)
    out, was_cut, _ = truncate_tool_result("some_custom_tool", big)
    assert was_cut is True
    assert len(out.encode("utf-8")) <= _DEFAULT_LIMIT


def test_sub_agent_has_4kb_limit():
    big = "x" * 5000
    _, was_cut, _ = truncate_tool_result("sub_agent", big)
    assert was_cut is True


def test_result_exactly_at_limit_not_truncated():
    """Exact-fit result should pass through untouched (boundary case)."""
    exact = "x" * 8192
    out, was_cut, original = truncate_tool_result("bash", exact)
    assert was_cut is False
    assert out == exact
    assert original == 8192


# ── env override ───────────────────────────────────────────────────────

def test_env_zero_disables_truncation(monkeypatch):
    """HARNESS_TOOL_RESULT_LIMIT_BYTES=0 turns truncation off entirely
    (for debugging — operator explicitly wants raw outputs)."""
    monkeypatch.setenv("HARNESS_TOOL_RESULT_LIMIT_BYTES", "0")
    big = "x" * 100_000
    out, was_cut, original = truncate_tool_result("bash", big)
    assert was_cut is False
    assert out == big
    assert original == 100_000


def test_env_override_changes_global_ceiling(monkeypatch):
    """A positive env value overrides ALL per-tool limits."""
    monkeypatch.setenv("HARNESS_TOOL_RESULT_LIMIT_BYTES", "2048")
    big = "x" * 3000
    out, was_cut, _ = truncate_tool_result("bash", big)
    assert was_cut is True
    assert len(out.encode("utf-8")) <= 2048

    # Affects codegraph too (normally 6144)
    out2, was_cut2, _ = truncate_tool_result("codegraph_explore", big)
    assert was_cut2 is True
    assert len(out2.encode("utf-8")) <= 2048


def test_env_too_small_raises(monkeypatch):
    """Values below MIN_LIMIT (512) are operator typos — fail loud."""
    monkeypatch.setenv("HARNESS_TOOL_RESULT_LIMIT_BYTES", "100")
    with pytest.raises(RuntimeError, match="too small"):
        truncate_tool_result("bash", "x")


def test_env_garbage_raises(monkeypatch):
    monkeypatch.setenv("HARNESS_TOOL_RESULT_LIMIT_BYTES", "soon")
    with pytest.raises(RuntimeError, match="not an integer"):
        truncate_tool_result("bash", "x")


# ── UTF-8 safety ───────────────────────────────────────────────────────

def test_multibyte_utf8_not_split():
    """Truncation must not split a multibyte sequence — that would corrupt
    JSON serialization downstream. Build a string where the cut point lands
    in the middle of a 3-byte CJK char."""
    # Each '中' is 3 bytes in UTF-8. Bash limit is 8192 bytes = 2730.6 chars.
    # Filling past 8192 bytes forces a cut mid-char.
    text = "中" * 3000  # 9000 bytes
    out, was_cut, _ = truncate_tool_result("bash", text)
    assert was_cut is True
    # The result must be valid UTF-8 (decodable without errors)
    out.encode("utf-8").decode("utf-8")  # raises if corrupted
    # And end on a complete char (no replacement char from decode-with-ignore)
    assert not out.rstrip().endswith("�")


# ── truncation_context + event emission ───────────────────────────────

def test_emit_outside_context_is_noop():
    """No context set → silently no-op (e.g. tests calling tools directly)."""
    # Should not raise.
    emit_tool_output_truncated(
        tool_name="bash",
        original_bytes=10000,
        truncated_bytes=8192,
        limit_bytes=8192,
    )


def test_emit_with_context_fires_event():
    """Inside truncation_context, emit_tool_output_truncated calls bus.emit."""
    events: list[tuple[str, dict]] = []

    class _StubBus:
        def emit(self, event_type, payload, **kw):
            events.append((event_type, payload))

    bus = _StubBus()
    with truncation_context(bus, "wf-1", "node-1", "agent-1"):
        emit_tool_output_truncated(
            tool_name="bash",
            original_bytes=10000,
            truncated_bytes=8192,
            limit_bytes=8192,
        )

    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == "agent.tool_output_truncated"
    assert payload["workflow_id"] == "wf-1"
    assert payload["node_id"] == "node-1"
    assert payload["agent_name"] == "agent-1"
    assert payload["tool_name"] == "bash"
    assert payload["original_bytes"] == 10000
    assert payload["truncated_bytes"] == 8192
    assert payload["limit_bytes"] == 8192


def test_context_nested_inner_overrides_outer():
    """Nested contexts (e.g. sub_agent calling a tool in its own iter)
    must use the innermost context's bus/routing — same semantics as
    contextvars generally provide."""
    outer_events: list[tuple[str, dict]] = []
    inner_events: list[tuple[str, dict]] = []

    class _Bus:
        def __init__(self, sink):
            self._sink = sink
        def emit(self, event_type, payload, **kw):
            self._sink.append((event_type, payload))

    outer_bus = _Bus(outer_events)
    inner_bus = _Bus(inner_events)

    with truncation_context(outer_bus, "wf-outer", "n-outer", "a-outer"):
        with truncation_context(inner_bus, "wf-inner", "n-inner", "a-inner"):
            emit_tool_output_truncated(
                tool_name="bash", original_bytes=100, truncated_bytes=80, limit_bytes=80,
            )

    # Inner context wins
    assert len(inner_events) == 1
    assert inner_events[0][1]["workflow_id"] == "wf-inner"
    # Outer bus didn't see it
    assert outer_events == []


def test_emit_with_none_bus_is_silent():
    """bus=None inside context (e.g. CLI / script mode) — no crash, no event."""
    with truncation_context(None, "wf", "n", "a"):
        emit_tool_output_truncated(
            tool_name="bash", original_bytes=100, truncated_bytes=80, limit_bytes=80,
        )
