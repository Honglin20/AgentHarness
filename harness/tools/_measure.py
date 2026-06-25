"""Emit per-tool-call measurement events (bytes + tokens).

Companion to ``_truncate.py``'s truncation event. Where
``emit_tool_output_truncated`` fires only when a result is cut down,
``emit_tool_output_measured`` fires for EVERY tool call — recording the
original (pre-truncation) and final (post-truncation) sizes in both bytes
and tokens. This is the data source for token audits (which tool, how many
tokens, how much was reclaimed by truncation).

Reuses the same ``truncation_context`` contextvar as truncation: the
(bus, workflow_id, node_id, agent_name) tuple is published by
``LLMExecutor.run()`` and read here best-effort. Emission outside a context
(e.g. tools exercised directly in tests) is a silent no-op — measurement
must never break a tool call.

Event: ``agent.tool_output_measured``
Payload: {workflow_id, node_id, agent_name, tool_name, original_bytes,
          truncated_bytes, original_tokens, truncated_tokens, counter}
"""
from __future__ import annotations

import logging
from typing import Any

from harness.tools._truncate import _truncation_ctx
from harness.tools.token_counter import get_token_counter

logger = logging.getLogger(__name__)


def _byte_len(s: Any) -> int:
    """UTF-8 byte length of a result, tolerating non-str results."""
    if isinstance(s, (bytes, bytearray)):
        return len(s)
    if isinstance(s, str):
        return len(s.encode("utf-8"))
    # Non-string tool results (rare) — stringify so we still get a number.
    try:
        return len(str(s).encode("utf-8"))
    except Exception:
        return 0


def emit_tool_output_measured(
    tool_name: str,
    original: Any,
    truncated: Any,
) -> None:
    """Emit ``agent.tool_output_measured`` for one tool call.

    Computes bytes + tokens for both the pre-truncation ``original`` and the
    post-truncation ``truncated`` result. No-op outside a
    ``truncation_context`` (no bus) — measurement is best-effort telemetry.

    Token counting uses :func:`get_token_counter`; failures there are caught
    so a tokenizer hiccup can't break the tool call.
    """
    ctx = _truncation_ctx.get()
    if ctx is None:
        return
    bus, wid, node_id, agent_name = ctx
    if bus is None:
        return

    try:
        original_bytes = _byte_len(original)
        truncated_bytes = _byte_len(truncated)
        counter = get_token_counter()
        original_tokens = counter.count(original) if isinstance(original, str) else 0
        truncated_tokens = counter.count(truncated) if isinstance(truncated, str) else 0

        bus.emit("agent.tool_output_measured", {
            "workflow_id": wid,
            "node_id": node_id,
            "agent_name": agent_name,
            "tool_name": tool_name,
            "original_bytes": original_bytes,
            "truncated_bytes": truncated_bytes,
            "original_tokens": original_tokens,
            "truncated_tokens": truncated_tokens,
            "counter": counter.name,
        })
    except Exception:
        # Never let measurement break the tool call. The truncation already
        # happened upstream; this is best-effort telemetry.
        logger.debug("Failed to emit agent.tool_output_measured", exc_info=True)
