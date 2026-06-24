"""Pre/PostToolUse dispatch — the tool lifecycle hook entry points.

These are called from ``ToolFactory._wrap_fn`` (the universal tool chokepoint)
to give registered middleware a chance to act on each tool call:

  - ``dispatch_before_tool`` (PreToolUse): may rewrite args or block the call.
  - ``dispatch_after_tool``  (PostToolUse): may replace/flag the result.

Like ``_measure.py`` and ``_truncate.py``, they read the runtime context
(bus, workflow_id, node_id, agent_name) from the ``truncation_context``
contextvar set by ``LLMExecutor.run()`` — so they need no back-reference to
the executor.

Robustness contract (critical):
  - No bus / no ToolCtx / no middleware  → fast no-op, returns the original
    (``None`` for before, the input ``result`` for after). Zero overhead.
  - Any middleware exception             → logged + that middleware skipped;
    the call proceeds with the original value. A broken extension can NEVER
    block or corrupt a tool call.
  - ``RejectAction`` from before_tool    → caller short-circuits (returns the
    block reason to the model instead of executing).
  - ``SubstituteAction`` from after_tool → caller swaps in ``.result``.
  - ``RejectAction`` from after_tool     → caller treats the result as an
    error string for the model.

Async-only dispatch: ``_wrap_fn`` wraps the *raw* tool fn. pydantic-ai runs
sync tool fns in an executor thread, so a sync ``_wrap_fn`` branch would be
outside the event loop and could not ``await`` the (async) middleware chain.
To keep ONE dispatch path for every tool — including the sync heavy-output
tools (bash/grep/glob) that most need PostToolUse compaction — ``_wrap_fn``
detects sync fns and runs them via ``anyio.to_thread`` from an async wrapper,
so dispatch always happens on the loop. See ``registry._wrap_fn``.
"""
from __future__ import annotations

import logging
from typing import Any

from harness.extensions.base import (
    NodeCtx,
    RejectAction,
    SubstituteAction,
    ToolCtx,
    WorkflowCtx,
)
from harness.tools._truncate import _truncation_ctx

logger = logging.getLogger(__name__)


def _build_tool_ctx(tool_name: str, tool_args: dict[str, Any]) -> ToolCtx | None:
    """Construct a ToolCtx from the truncation_context contextvar.

    Returns None when there is no published context (tools run outside an
    LLMExecutor, e.g. direct unit tests) — callers treat that as "no hooks".
    """
    ctx = _truncation_ctx.get()
    if ctx is None:
        return None
    _bus, wid, node_id, agent_name = ctx
    # Build the lightweight contexts middleware expects. inputs/metadata are
    # not available at tool-call depth; they're left empty — middleware that
    # needs them should read from NodeCtx.metadata, which we don't fabricate.
    wctx = WorkflowCtx(workflow_id=wid, workflow_name="", inputs={})
    nctx = NodeCtx(
        workflow=wctx,
        node_id=node_id,
        agent_name=agent_name,
        prompt="",
        messages=[],
        upstream_outputs={},
    )
    return ToolCtx(node=nctx, tool_name=tool_name, tool_args=dict(tool_args))


def _bus() -> Any | None:
    """Return the bus from truncation_context, or None."""
    ctx = _truncation_ctx.get()
    if ctx is None:
        return None
    return ctx[0]


def _has_middleware() -> bool:
    """Fast-path check: is there any middleware at all on the bus?

    ``_wrap_fn`` calls this before constructing a ToolCtx / awaiting, so the
    common case (no middleware registered) costs one contextvar read + one
    attribute lookup, not a full dispatch.
    """
    bus = _bus()
    if bus is None:
        return False
    mw = getattr(bus, "_middleware", None)
    return bool(mw)


async def dispatch_before_tool(
    tool_name: str, tool_args: dict[str, Any],
) -> RejectAction | None:
    """PreToolUse dispatch. Returns RejectAction to block, else None (proceed).

    Fast-path: no middleware → None immediately. All dispatch is wrapped so
    an exception never propagates into the tool call.
    """
    if not _has_middleware():
        return None
    bus = _bus()
    tctx = _build_tool_ctx(tool_name, tool_args)
    if tctx is None:
        return None
    try:
        result = await bus.run_middleware_chain("before_tool", tctx)
        if isinstance(result, RejectAction):
            return result
        return None
    except Exception:
        logger.debug("before_tool dispatch failed", exc_info=True)
        return None


async def dispatch_after_tool(
    tool_name: str, tool_args: dict[str, Any], result: Any,
) -> Any:
    """PostToolUse dispatch. Returns the (possibly substituted) result.

    - SubstituteAction → the new result string
    - RejectAction     → an error string for the model
    - otherwise        → the original ``result`` (no-op)

    Fast-path: no middleware → returns ``result`` unchanged. Any exception →
    returns ``result`` unchanged (best-effort, never corrupts).
    """
    if not _has_middleware():
        return result
    bus = _bus()
    tctx = _build_tool_ctx(tool_name, tool_args)
    if tctx is None:
        return result
    try:
        outcome = await bus.run_middleware_chain("after_tool", (tctx, result))
        if isinstance(outcome, SubstituteAction):
            return outcome.result
        if isinstance(outcome, RejectAction):
            return f"[tool {tool_name} result rejected by policy: {outcome.reason}]"
        # outcome is the (ctx, result) tuple → unwrap the (possibly same) result.
        if isinstance(outcome, tuple) and len(outcome) == 2:
            return outcome[1]
        return result
    except Exception:
        logger.debug("after_tool dispatch failed", exc_info=True)
        return result
