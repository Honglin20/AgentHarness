"""TokenStatsHook — per-tool token consumption auditor.

An opt-in observer (NOT auto-registered) that tallies how many tokens each
tool's output contributes to the model's context. Use it to answer "which
tool is eating my context budget?" — the data baseline for the
OutputCompactor (TASK 3) and any future PreToolUse guardrail.

Design:
  - Pure observer: counts results, never returns SubstituteAction/RejectAction.
    Stats collection must not alter behavior (verifiable: a run with vs.
    without this hook produces identical agent output).
  - Counts the MODEL-VISIBLE result (post-truncation), via on_tool_call —
    i.e. what actually lands in message_history and is re-sent every turn.
    This is the token cost that matters. Pre-truncation sizes remain
    available on the ``agent.tool_output_measured`` event for deep analysis.
  - Reports on workflow end: a per-tool table (calls / total tokens /
    max single / mean) printed to stdout AND emitted as an
    ``agent.token_stats`` event for the frontend / log consumers.

Usage::

    from harness.extensions.hooks.token_stats import TokenStatsHook
    workflow.use(TokenStatsHook())
    # ... run ...
    report = hook.report()  # dict, also printed on workflow end
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from harness.extensions.base import BaseHook, NodeCtx, ToolCtx, WorkflowCtx
from harness.tools.token_counter import get_token_counter

logger = logging.getLogger(__name__)


@dataclass
class ToolStats:
    """Accumulated stats for one tool name."""
    calls: int = 0
    total_tokens: int = 0
    total_bytes: int = 0
    max_tokens: int = 0
    # Sample of the largest single result (truncated) for debugging which
    # call blew up the budget. Capped to avoid memory growth.
    max_sample: str = ""

    @property
    def mean_tokens(self) -> float:
        return self.total_tokens / self.calls if self.calls else 0.0


_SAMPLE_CAP = 200  # chars kept from the largest result, for the report


class TokenStatsHook(BaseHook):
    """Tally per-tool model-visible token consumption; report on workflow end.

    Register via ``workflow.use(TokenStatsHook())``. Not auto-registered —
    it's an opt-in audit tool, not default observation.
    """

    name = "token-stats"

    def __init__(self, verbose: bool = True) -> None:
        # Single per-tool aggregate for this hook instance's lifetime. A hook
        # instance is normally used for one run, so a flat dict is simpler and
        # more robust than keying by workflow_id (which can be empty/fragile
        # depending on how the executor populates NodeCtx.workflow).
        self._stats: dict[str, ToolStats] = {}
        self._counter = get_token_counter()
        self._verbose = verbose

    # ---- collection ----

    async def on_tool_call(self, ctx: ToolCtx, result: Any) -> None:
        """Count the model-visible result for this tool call."""
        stats = self._stats.setdefault(ctx.tool_name, ToolStats())
        text = result if isinstance(result, str) else str(result)
        toks = self._counter.count(text)
        nbytes = len(text.encode("utf-8"))
        stats.calls += 1
        stats.total_tokens += toks
        stats.total_bytes += nbytes
        if toks > stats.max_tokens:
            stats.max_tokens = toks
            stats.max_sample = text[:_SAMPLE_CAP]

    # ---- reporting ----

    async def on_workflow_end(self, ctx: WorkflowCtx, result: dict[str, Any]) -> None:
        report = self.report()
        if self._verbose:
            self._print_report(getattr(ctx, "workflow_id", "?"), report)
        # Emit for frontend / structured consumers. WorkflowCtx has no emit()
        # in the current contract (only NodeCtx does); keep this defensive so
        # the hook never crashes on_end. The report is always available via
        # report() and printed when verbose.
        emit = getattr(ctx, "emit", None)
        if callable(emit):
            emit("agent.token_stats", {
                "workflow_id": getattr(ctx, "workflow_id", ""),
                "tools": {
                    name: {
                        "calls": s.calls,
                        "total_tokens": s.total_tokens,
                        "total_bytes": s.total_bytes,
                        "max_tokens": s.max_tokens,
                        "mean_tokens": round(s.mean_tokens, 1),
                    }
                    for name, s in report.items()
                },
            })

    def report(self, workflow_id: str | None = None) -> dict[str, ToolStats]:
        """Return the per-tool stats dict.

        ``workflow_id`` is accepted for API stability but ignored — a hook
        instance tracks one aggregate (normally one run = one instance).
        """
        return dict(self._stats)

    def _print_report(self, wid: str, report: dict[str, ToolStats]) -> None:
        if not report:
            print(f"\n[token-stats] {wid}: no tool calls recorded")
            return
        total = sum(s.total_tokens for s in report.values())
        total_calls = sum(s.calls for s in report.values())
        print(f"\n{'═' * 64}")
        print(f"  TOKEN AUDIT — workflow {wid}")
        print(f"  counter: {self._counter.name}  |  total: {total} tokens / {total_calls} calls")
        print(f"{'─' * 64}")
        print(f"  {'tool':<18}{'calls':>6}{'tokens':>10}{'max':>8}{'mean':>8}")
        print(f"  {'-' * 18}{'-' * 6}{'-' * 10}{'-' * 8}{'-' * 8}")
        for name, s in sorted(report.items(), key=lambda kv: -kv[1].total_tokens):
            print(
                f"  {name:<18}{s.calls:>6}{s.total_tokens:>10}"
                f"{s.max_tokens:>8}{s.mean_tokens:>8.0f}"
            )
        print(f"{'═' * 64}\n")
