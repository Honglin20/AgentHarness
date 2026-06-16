"""Tool result truncation — bounds message_history growth.

Long tool returns (bash output, codegraph_explore source dumps, sub_agent
final reports) are added verbatim to Pydantic AI's message_history by the
call_tools_node. Every subsequent model request ships the full history, so
a single 10KB bash output inflates input_tokens by ~2.5k on every following
request — and accumulates across N tool calls.

Truncation lives in ToolFactory._wrap_fn so every tool goes through it
without per-tool opt-in. The truncation point reads runtime context
(workflow_id / node_id / bus) via contextvars set by LLMExecutor.run().

Per-tool limits (bytes of UTF-8 encoded text):
    bash / bash_background: 8192   (stdout can be huge)
    codegraph_*:           6144   (multi-file source dumps)
    sub_agent:             4096   (final report)
    grep_glob:             4096   (file list)
    default:               8192

Override globally via env HARNESS_TOOL_RESULT_LIMIT_BYTES (int, >= 512).
Set to 0 to disable truncation entirely (debugging only).
"""

from __future__ import annotations

import contextvars
import os
from typing import Any, Literal

# ── Per-tool byte limits ────────────────────────────────────────────────
#
# Keyed by exact tool name OR prefix (codegraph_* matches codegraph_search,
# codegraph_explore, etc.). Checked in order: exact match → prefix match →
# default. Limits are upper bounds — short results pass through untouched.

_TOOL_LIMITS_EXACT: dict[str, int] = {
    "bash": 8192,
    "bash_background": 8192,
    "sub_agent": 4096,
    "grep_glob": 4096,
    "grep": 4096,
    "glob": 4096,
}

_TOOL_LIMIT_PREFIXES: list[tuple[str, int]] = [
    ("codegraph_", 6144),
]

_DEFAULT_LIMIT = 8192
_MIN_LIMIT = 512  # below this truncation makes no sense — output is too short
_TAIL_NOTICE = (
    "\n\n[... truncated {removed} bytes — use codegraph_node for full source, "
    "or Read with offset/limit for files]"
)


def _resolve_limit(tool_name: str) -> int:
    """Return the effective byte limit for tool_name, honoring env override.

    HARNESS_TOOL_RESULT_LIMIT_BYTES:
      unset / < 0: use per-tool dictionary defaults
      0:           truncation disabled (caller will short-circuit)
      >= 512:      overrides ALL per-tool limits (single global ceiling)
      1..511:      invalid, raises (operator typo protection)
    """
    raw = os.environ.get("HARNESS_TOOL_RESULT_LIMIT_BYTES")
    if raw is None or raw == "":
        return _lookup_per_tool_limit(tool_name)
    try:
        n = int(raw)
    except ValueError:
        raise RuntimeError(
            f"HARNESS_TOOL_RESULT_LIMIT_BYTES={raw!r} is not an integer. "
            "Use 0 to disable truncation, or a positive integer >= 512."
        )
    if n == 0:
        return 0
    if n < _MIN_LIMIT:
        raise RuntimeError(
            f"HARNESS_TOOL_RESULT_LIMIT_BYTES={n} is too small. "
            f"Use 0 to disable, or >= {_MIN_LIMIT}."
        )
    return n


def _lookup_per_tool_limit(tool_name: str) -> int:
    if tool_name in _TOOL_LIMITS_EXACT:
        return _TOOL_LIMITS_EXACT[tool_name]
    for prefix, limit in _TOOL_LIMIT_PREFIXES:
        if tool_name.startswith(prefix):
            return limit
    return _DEFAULT_LIMIT


def truncate_tool_result(
    tool_name: str,
    result: Any,
) -> tuple[Any, bool, int]:
    """Apply size limit to a tool's return value.

    Args:
        tool_name: registered tool name (e.g. "bash", "codegraph_explore")
        result: the tool's return value — usually str, but may be other
            types for non-string tools (dicts, None). Non-str values pass
            through untouched (we don't know how to truncate them safely).

    Returns:
        (truncated_result, was_truncated, original_bytes)
        - was_truncated=False means result is unchanged
        - original_bytes is the UTF-8 byte length of the original (0 if non-str)
    """
    limit = _resolve_limit(tool_name)
    if limit == 0:
        # Truncation disabled via env
        if isinstance(result, str):
            return result, False, len(result.encode("utf-8"))
        return result, False, 0

    if not isinstance(result, str):
        # Non-string returns (None, dict, list, int) — leave alone. Most
        # tools return str; the few that don't (chart.py returns chart data
        # via event side-channel) are bounded by other mechanisms.
        return result, False, 0

    original_bytes = len(result.encode("utf-8"))
    if original_bytes <= limit:
        return result, False, original_bytes

    # Reserve room for the tail notice so the final payload ≤ limit.
    notice = _TAIL_NOTICE.format(removed=original_bytes - limit)
    notice_bytes = len(notice.encode("utf-8"))
    # Cut the body so body + notice ≤ limit. If notice itself > limit
    # (extreme: limit=512 with huge result), still leave at least half
    # the limit for actual content.
    body_budget = max(limit - notice_bytes, limit // 2)
    truncated_body = result[:body_budget]
    # Walk back to a UTF-8 char boundary to avoid emitting half a multibyte
    # sequence (which would crash JSON serialization downstream).
    truncated_body = _safe_utf8_cut(truncated_body)
    final = truncated_body + notice
    return final, True, original_bytes


def _safe_utf8_cut(s: str) -> str:
    """If s ends with an incomplete UTF-8 sequence, trim it.

    Python str slicing by character count is safe — but we sliced by byte
    budget via len(s.encode()). result[:body_budget] indexes by CHARACTER,
    not byte, so the actual encoded length may overshoot. Re-encode and
    cut at byte boundary, then decode.
    """
    encoded = s.encode("utf-8")
    # Decode with errors='ignore' as a safety net; we already cut on a char
    # boundary by indexing the original str, so this should be a no-op.
    return encoded.decode("utf-8", errors="ignore")


# ── Runtime context for truncated-event emission ───────────────────────
#
# ToolFactory._wrap_fn runs at tool-call time deep inside Pydantic AI's
# call_tools_node, far from LLMExecutor. To emit agent.tool_output_truncated
# events with the right (workflow_id, node_id, agent_name, bus) we use a
# contextvar set by LLMExecutor.run() at iter entry.

_TruncationCtx = tuple[Any, str, str, str]  # (bus, workflow_id, node_id, agent_name)
_truncation_ctx: contextvars.ContextVar[_TruncationCtx | None] = contextvars.ContextVar(
    "_truncation_ctx", default=None,
)


class truncation_context:
    """Context manager that publishes (bus, workflow_id, node_id, agent_name)
    for the duration of an LLMExecutor.run() call.

    Used so ToolFactory._wrap_fn can emit agent.tool_output_truncated events
    without holding a back-reference to the executor. Mirrors the chart.py
    set_chart_workflow_context pattern.

    Usage::

        with truncation_context(bus, wid, node_id, agent_name):
            async with agent.iter(...) as run:
                ...
    """

    def __init__(
        self,
        bus: Any | None,
        workflow_id: str,
        node_id: str,
        agent_name: str,
    ) -> None:
        self._bus = bus
        self._wid = workflow_id
        self._node_id = node_id
        self._agent_name = agent_name
        self._token: contextvars.Token[_TruncationCtx | None] | None = None

    def __enter__(self) -> "truncation_context":
        self._token = _truncation_ctx.set(
            (self._bus, self._wid, self._node_id, self._agent_name)
        )
        return self

    def __exit__(self, *exc: Any) -> Literal[False]:
        if self._token is not None:
            _truncation_ctx.reset(self._token)
            self._token = None
        return False


def emit_tool_output_truncated(
    tool_name: str,
    original_bytes: int,
    truncated_bytes: int,
    limit_bytes: int,
) -> None:
    """Emit agent.tool_output_truncated if a bus was published via
    truncation_context. No-op when called outside a context (e.g. tests
    that exercise tools directly without an executor).
    """
    ctx = _truncation_ctx.get()
    if ctx is None:
        return
    bus, wid, node_id, agent_name = ctx
    if bus is None:
        return
    try:
        bus.emit("agent.tool_output_truncated", {
            "workflow_id": wid,
            "node_id": node_id,
            "agent_name": agent_name,
            "tool_name": tool_name,
            "original_bytes": original_bytes,
            "truncated_bytes": truncated_bytes,
            "limit_bytes": limit_bytes,
        })
    except Exception:
        # Never let event emission break the tool call. The truncation
        # itself already happened; this is best-effort telemetry.
        import logging
        logging.getLogger(__name__).debug(
            "Failed to emit agent.tool_output_truncated", exc_info=True,
        )
