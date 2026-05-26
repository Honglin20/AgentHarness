"""AutoCompact — automatic context compression middleware.

When the messages history grows past a token threshold, AutoCompact replaces
all-but-the-most-recent messages with a single LLM-generated summary. This
keeps long workflows within the model's context window without manual
intervention.

Design notes
------------
- Implemented as a Middleware (mutates ctx.messages in `before_node`).
- Runs **late** in the before_node chain (priority 100) so that memory/
  guardrail extensions inject their content first, and we then compact
  the combined whole.
- Uses pydantic_ai for the summary LLM call so it inherits the project's
  model/api-key configuration. Defaults to the same model the workflow
  uses, but accepts an override via `summarizer_model`.
- Token counting: heuristic (chars / 4). If you need accuracy, pass a
  custom token_counter callable.

Usage
-----
    from harness.api import Workflow
    from harness.extensions.compact import AutoCompact

    wf = (
        Workflow("research", agents=[...])
        .use(AutoCompact(threshold_tokens=8000, keep_recent=4))
    )

Tests
-----
- Unit: test_auto_compact.py — mocks the summarizer to verify the
  truncate-and-summarize logic in isolation.
- Integration: test_auto_compact_integration.py — registers it on a
  real Bus and runs the middleware chain end-to-end.
- Off-state: tests cover that when not registered, NodeCtx.messages is
  untouched (enforced by the empty-bus contract in test_bus.py).
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from harness.extensions.base import BaseMiddleware, NodeCtx

# Default summary prompt — kept conservative; users can override.
_DEFAULT_SUMMARY_PROMPT = (
    "Summarize the conversation below in <= 200 words. Preserve "
    "concrete facts, decisions made, and any unresolved questions. "
    "Drop pleasantries and repeated content. Output the summary only."
)

TokenCounter = Callable[[str], int]
Summarizer = Callable[[str], Awaitable[str]]


def _heuristic_count(text: str) -> int:
    """Cheap token estimate: 4 chars ≈ 1 token. Good enough for thresholds."""
    return max(1, len(text) // 4)


async def _default_summarizer(text: str, model: Optional[str] = None) -> str:
    """LLM-backed summarizer. Imports pydantic_ai lazily so unit tests
    that mock the Summarizer don't trigger network/api-key requirements.
    """
    from pydantic_ai import Agent as PaiAgent  # local import
    agent = PaiAgent(model=model, system_prompt=_DEFAULT_SUMMARY_PROMPT)
    result = await agent.run(text)
    return str(result.output) if hasattr(result, "output") else str(result)


class AutoCompact(BaseMiddleware):
    """Compress long message histories before the LLM call.

    Parameters
    ----------
    threshold_tokens : int
        Total messages token count above which compaction triggers.
    keep_recent : int
        Number of most-recent messages to keep verbatim.
    summarizer : Optional[Callable]
        Custom async function `(text: str) -> str`. Defaults to a
        pydantic_ai-based summarizer using the workflow's default model.
    summarizer_model : Optional[str]
        Model id passed to the default summarizer (e.g. "openai:gpt-4o-mini").
        Ignored if `summarizer` is set.
    token_counter : Optional[Callable]
        Custom `(text: str) -> int`. Defaults to the cheap heuristic.
    enabled : bool
        Master switch. When False, this middleware becomes a no-op.
    """

    name = "auto_compact"
    priority = 100  # late in before_node chain

    def __init__(
        self,
        threshold_tokens: int = 8000,
        keep_recent: int = 4,
        summarizer: Summarizer | None = None,
        summarizer_model: str | None = None,
        token_counter: TokenCounter | None = None,
        enabled: bool = True,
    ):
        if keep_recent < 1:
            raise ValueError("keep_recent must be >= 1")
        if threshold_tokens < 100:
            raise ValueError("threshold_tokens must be >= 100")
        self.threshold_tokens = threshold_tokens
        self.keep_recent = keep_recent
        self.enabled = enabled
        self._summarizer = summarizer
        self._summarizer_model = summarizer_model
        self._count = token_counter or _heuristic_count

    async def _summarize(self, text: str) -> str:
        if self._summarizer is not None:
            return await self._summarizer(text)
        return await _default_summarizer(text, model=self._summarizer_model)

    async def before_node(self, ctx: NodeCtx) -> NodeCtx:
        if not self.enabled:
            return ctx
        if len(ctx.messages) <= self.keep_recent:
            return ctx

        total = sum(self._count(self._stringify(m)) for m in ctx.messages)
        if total < self.threshold_tokens:
            return ctx

        early = ctx.messages[: -self.keep_recent]
        recent = ctx.messages[-self.keep_recent :]
        joined = "\n\n".join(self._format_for_summary(m) for m in early)
        summary = await self._summarize(joined)

        summary_msg = {
            "role": "system",
            "content": f"[Compacted earlier context]: {summary}",
        }
        ctx.messages = [summary_msg] + recent

        # Annotate metadata so observers / UI know it happened
        ctx.metadata.setdefault(self.name, {})
        ctx.metadata[self.name]["compacted"] = True
        ctx.metadata[self.name]["original_token_estimate"] = total
        ctx.metadata[self.name]["dropped_messages"] = len(early)
        return ctx

    # ----- helpers -----

    @staticmethod
    def _stringify(msg: dict) -> str:
        c = msg.get("content", "")
        return c if isinstance(c, str) else str(c)

    @staticmethod
    def _format_for_summary(msg: dict) -> str:
        role = msg.get("role", "?")
        return f"[{role}] {AutoCompact._stringify(msg)}"
