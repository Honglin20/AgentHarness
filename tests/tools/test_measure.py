"""TASK 0 acceptance: tool-output measurement infrastructure.

Covers the five acceptance criteria:
  1. measurement covers every tool call (emit fires once per call)
  2. zero behavior change without hooks/middleware (result unchanged)
  3. tokenizer correctness (TiktokenCounter == tiktoken direct)
  4. robust fallback (tiktoken failure → HeuristicCounter, no crash)
  5. measurement never pollutes the tool result (emit failure tolerated)
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from harness.tools._measure import _byte_len, emit_tool_output_measured
from harness.tools._truncate import truncation_context
from harness.tools.token_counter import (
    HeuristicCounter,
    TiktokenCounter,
    get_token_counter,
    set_token_counter,
)


# ── criterion 3: tokenizer correctness ────────────────────────────────


class TestTiktokenCounter:
    def test_count_matches_tiktoken_directly(self):
        import tiktoken

        counter = TiktokenCounter("gpt-4o")
        text = "hello world — measure twice, cut once"
        assert counter.count(text) == len(
            counter._enc.encode(text, disallowed_special=())
        )

    def test_empty_string_is_zero(self):
        assert TiktokenCounter("gpt-4o").count("") == 0

    def test_unknown_model_falls_back_to_cl100k_base(self):
        """Models tiktoken can't map get cl100k_base (still counts, no crash)."""
        c = TiktokenCounter("some-future-model-xyz")
        assert c.count("hello world") > 0
        assert "cl100k_base" in c.name

    def test_name_encodes_basis(self):
        assert TiktokenCounter("gpt-4o").name == "tiktoken:gpt-4o"
        assert "cl100k_base" in TiktokenCounter("nope").name


class TestHeuristicCounter:
    def test_approx_4_chars_per_token(self):
        assert HeuristicCounter().count("abcdefgh") == 2  # 8 chars // 4

    def test_empty_is_zero(self):
        assert HeuristicCounter().count("") == 0

    def test_nonzero_floor(self):
        """A short non-empty string still counts as >= 1 token."""
        assert HeuristicCounter().count("a") == 1


# ── criterion 4: robust fallback ───────────────────────────────────────


class TestFallback:
    def test_get_token_counter_returns_singleton(self):
        set_token_counter(None)  # reset
        c1 = get_token_counter()
        c2 = get_token_counter()
        assert c1 is c2

    def test_set_token_counter_override(self):
        custom = HeuristicCounter()
        set_token_counter(custom)
        assert get_token_counter() is custom
        set_token_counter(None)  # cleanup

    def test_tiktoken_failure_degrades_gracefully(self, monkeypatch):
        """If tiktoken import fails, get_token_counter must not crash."""
        import harness.tools.token_counter as tc_mod

        def _boom(model=None):
            raise RuntimeError("simulated tiktoken unavailable")

        monkeypatch.setattr(tc_mod, "TiktokenCounter", _boom)
        monkeypatch.delenv("HARNESS_TOKENIZER_MODEL", raising=False)
        monkeypatch.delenv("HARNESS_MODEL", raising=False)
        set_token_counter(None)
        c = get_token_counter()
        assert isinstance(c, HeuristicCounter)
        set_token_counter(None)  # cleanup


# ── criterion 1 + 5: emit behavior ─────────────────────────────────────


def _fake_bus():
    """A bus mock that records emitted events."""
    bus = MagicMock()
    bus.emit = MagicMock()
    return bus


class TestEmitToolOutputMeasured:
    def test_emits_once_per_call_with_all_fields(self):
        bus = _fake_bus()
        with truncation_context(bus, "wf", "node1", "agent_a"):
            emit_tool_output_measured("bash", "x" * 100, "x" * 40)
        assert bus.emit.call_count == 1
        event_type, payload = bus.emit.call_args[0]
        assert event_type == "agent.tool_output_measured"
        assert payload["tool_name"] == "bash"
        assert payload["workflow_id"] == "wf"
        assert payload["node_id"] == "node1"
        assert payload["agent_name"] == "agent_a"
        assert payload["original_bytes"] == 100
        assert payload["truncated_bytes"] == 40
        assert payload["original_tokens"] >= payload["truncated_tokens"]
        assert payload["counter"]  # non-empty basis string

    def test_noop_outside_context(self):
        """No truncation_context → silent no-op (e.g. direct tool tests)."""
        bus = _fake_bus()
        emit_tool_output_measured("bash", "data", "data")
        bus.emit.assert_not_called()

    def test_noop_when_bus_is_none(self):
        with truncation_context(None, "wf", "node1", "agent_a"):
            emit_tool_output_measured("bash", "data", "data")
        # No crash, no emit.

    def test_emit_failure_never_raises(self, caplog):
        """A broken bus.emit must not propagate — measurement is best-effort."""
        bus = MagicMock()
        bus.emit = MagicMock(side_effect=RuntimeError("bus broken"))
        with caplog.at_level(logging.DEBUG):
            with truncation_context(bus, "wf", "node1", "agent_a"):
                # Must not raise.
                emit_tool_output_measured("bash", "data", "data")

    def test_byte_len_handles_non_string(self):
        assert _byte_len("abc") == 3
        assert _byte_len(b"abc") == 3
        assert _byte_len(123) == 3  # str(123) = "123"
        assert _byte_len(None) == 4  # str(None) = "None"


# ── criterion 2: zero behavior change ──────────────────────────────────


class TestZeroBehaviorChange:
    """The measurement emit must not alter the tool result that reaches the model."""

    async def test_wrap_fn_returns_truncated_result_unchanged(self):
        """_wrap_fn output is byte-identical with/without measurement, because
        emit_tool_output_measured is a fire-and-forget side channel."""
        from harness.tools.bash import BashToolFactory

        # Drive a real (fast, harmless) bash tool call through the wrapped fn.
        factory = BashToolFactory(timeout_ms=5000)
        tool = factory.create()
        bash_fn = tool.function
        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.deps.workdir = "."
        ctx.deps.workflow_id = "w"
        ctx.deps.node_id = "n"
        ctx.deps.agent_name = "a"
        ctx.deps.__class__ = type("D", (), {})

        # The result the model sees is whatever bash returns; measurement must
        # not transform it. We assert the result still contains the echo output.
        result = await bash_fn(ctx, command="echo measurement-test", description="t")
        assert "measurement-test" in result


# ── end-to-end: measurement fires within a truncation_context ──────────


class TestMeasurementThroughWrapFn:
    """A tool call inside a truncation_context emits exactly one measured event."""

    async def test_bash_call_emits_measured_event(self):
        from harness.tools.bash import BashToolFactory

        bus = _fake_bus()
        factory = BashToolFactory(timeout_ms=5000)
        tool = factory.create()
        bash_fn = tool.function

        ctx = MagicMock()
        ctx.deps.workdir = "."
        ctx.deps.workflow_id = "w"
        ctx.deps.node_id = "n"
        ctx.deps.agent_name = "a"

        # Bash uses run_foreground internally; we need a real CWD.
        import os
        ctx.deps.__class__ = type("D", (), {})

        with truncation_context(bus, "w", "n", "a"):
            await bash_fn(ctx, command="echo hi", description="t")

        measured = [
            c for c in bus.emit.call_args_list
            if c[0] and c[0][0] == "agent.tool_output_measured"
        ]
        assert len(measured) == 1, "exactly one measured event per tool call"
        assert measured[0][0][1]["tool_name"] == "bash"
