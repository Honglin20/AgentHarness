"""OutputCompactor — PostToolUse middleware that reclaims context tokens.

Counterpart to Claude Code's PostToolUse output-cleaning. The framework's
universal truncation (``_wrap_fn`` → ``truncate_tool_result``) already caps
each tool result at a per-tool BYTE limit. This middleware adds a TOKEN-aware
second pass: any result still over ``threshold_tokens`` after truncation is
compacted to a head+tail preview, with the full text spilled to disk and a
pointer left for the model to recover it via ``read_text_file``.

Why a separate pass when truncation exists:
  - Truncation is byte-based and per-tool-fixed (bash=8KB). A result can be
    under the byte cap yet still cost hundreds of tokens every turn.
  - This is token-aware and configurable, so the budget is expressed in the
    unit that actually matters (context window).
  - It runs as MIDDLENGEWARE (after_tool), so it's explicit/auditable and
    composes with other PostToolUse strategies via the priority chain.

Design:
  - Returns SubstituteAction(result=...) when compacting — the explicit
    signal that the output was rewritten (debuggable, unlike silent replace).
  - Whitelist: tools whose results must pass through verbatim (TodoTool state,
    ask_user answers) — short, semantic, never worth compacting.
  - Spill: full text written under ``<workdir>/.tool_outputs/`` (mirrors
    bash's ``.bash_outputs``), pointer embedded in the compacted result so
    the model can recover the original with read_text_file.
  - Extension point: ``summarize`` is a callable strategy. The default is
    head+tail truncation; a future LLM-summarizing strategy drops in without
    touching this class (open/closed).
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from harness.extensions.base import BaseMiddleware, SubstituteAction, ToolCtx
from harness.tools.token_counter import get_token_counter

logger = logging.getLogger(__name__)

# Tools whose results are short + semantic — compacting them loses meaning
# for no token savings. These pass through verbatim.
_DEFAULT_WHITELIST: frozenset[str] = frozenset({
    "TodoTool",
    "ask_user",
})

# Default compaction threshold. Results at/above this many tokens get
# compacted. ~500 tokens ≈ 2KB — a deliberate floor so only genuinely large
# outputs (the audit's 777-token bash calls) are touched.
_DEFAULT_THRESHOLD_TOKENS = 500

# How many chars of head/tail to keep in the compacted preview.
_HEAD_CHARS = 600
_TAIL_CHARS = 400


@dataclass
class _Compaction:
    """Result of one compaction decision (for tests / reporting)."""
    tool_name: str
    original_tokens: int
    compacted_tokens: int
    spill_path: Path | None


def _default_summarize(text: str, head: int = _HEAD_CHARS, tail: int = _TAIL_CHARS) -> str:
    """Head+tail preview with an elision marker. Keeps the start (usually the
    most informative part — errors, headers) and the end (final status)."""
    if len(text) <= head + tail + 50:
        return text  # nothing meaningful to cut
    return (
        text[:head]
        + f"\n\n[… {len(text) - head - tail} chars elided — see spill path for full output …]\n\n"
        + text[-tail:]
    )


def _spill(workdir: str | None, tool_name: str, content: str) -> Path | None:
    """Write the full content to a deterministic file; return its path.

    Returns None if workdir is unknown (no spill, just summarize inline).
    """
    if not workdir:
        return None
    try:
        out_dir = Path(workdir) / ".tool_outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        h = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:8]
        path = out_dir / f"{ts}_{tool_name}_{h}.txt"
        path.write_text(content, encoding="utf-8", errors="replace")
        return path
    except Exception:
        logger.debug("OutputCompactor spill failed", exc_info=True)
        return None


class OutputCompactor(BaseMiddleware):
    """PostToolUse middleware: compact large tool results to reclaim tokens.

    Configure via constructor: ``OutputCompactor(threshold_tokens=500,
    whitelist={"TodoTool", ...}, workdir="/repo")``. Register with
    ``workflow.use(OutputCompactor(...))``.

    ``workdir``: where to spill full outputs. The single source — set via
    the constructor. If None, compaction still summarizes inline but cannot
    spill the full text (the model loses it — use a real workdir in
    production).

    ``summarize``: callable (text) -> str. Default is head+tail; swap for an
    LLM-summarizing strategy without subclassing.
    """

    name = "output-compactor"
    # Run late in the after_tool chain (high priority for after_* phases) so
    # other PostToolUse middleware see the already-compacted result.
    priority = 80

    def __init__(
        self,
        threshold_tokens: int = _DEFAULT_THRESHOLD_TOKENS,
        whitelist: frozenset[str] | set[str] | None = None,
        workdir: str | None = None,
        summarize: Callable[[str], str] = _default_summarize,
    ) -> None:
        self.threshold_tokens = threshold_tokens
        self.whitelist = frozenset(whitelist) if whitelist is not None else _DEFAULT_WHITELIST
        self.workdir = workdir
        self.summarize = summarize
        self._counter = get_token_counter()
        # Record of compactions this instance performed (for the before/after
        # comparison report and debugging).
        self.compactions: list[_Compaction] = []

    async def after_tool(self, ctx: ToolCtx, result: Any) -> Any | SubstituteAction:
        """Compact ``result`` if it exceeds the token threshold.

        Non-string results and whitelisted tools pass through unchanged.
        """
        if not isinstance(result, str):
            return result
        if ctx.tool_name in self.whitelist:
            return result

        toks = self._counter.count(result)
        if toks < self.threshold_tokens:
            return result  # under budget — leave untouched

        # workdir is the single source — set via the constructor. When None,
        # compaction summarizes inline but cannot spill the full text (the
        # model loses it). Production runs should pass a real workdir.
        workdir = self.workdir

        compacted = self.summarize(result)
        spill_path = _spill(workdir, ctx.tool_name, result)
        if spill_path is not None:
            compacted = (
                compacted
                + f"\n\n[full {toks}-token output spilled to: {spill_path} — "
                f"use read_text_file to recover it]"
            )

        compacted_tokens = self._counter.count(compacted)
        self.compactions.append(_Compaction(
            tool_name=ctx.tool_name,
            original_tokens=toks,
            compacted_tokens=compacted_tokens,
            spill_path=spill_path,
        ))
        return SubstituteAction(result=compacted)
