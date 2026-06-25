"""Pluggable token counter for tool-output measurement.

Measuring how many tokens each tool call consumes needs a tokenizer. The
framework proxies multiple model providers (OpenAI-compatible, DeepSeek,
…), whose tokenizers differ — so the counter is a swappable protocol with
two built-in implementations:

  - ``TiktokenCounter``  — exact for OpenAI-family models; falls back to
    ``cl100k_base`` for unknown models (a close approximation for most
    modern chat models). Encoder is cached per-model.
  - ``HeuristicCounter`` — ``len(text) // 4``; identical to
    ``AutoCompact._heuristic_count``. Used when tiktoken import fails or
    when callers want a dependency-free estimate.

The active counter is resolved once per process via :func:`get_token_counter`
and can be overridden (tests, custom tokenizers) via
:func:`set_token_counter`. Model name is read from the
``HARNESS_MODEL`` / ``HARNESS_TOKENIZER_MODEL`` env var at first access;
this keeps measurement aligned with the model the run actually uses.

Design rules
------------
- Protocol-first: callers depend on ``TokenCounter``, never on a concrete
  class, so a future Claude/Gemini-native tokenizer drops in without
  touching call sites.
- Pure: ``count()`` has no side effects and never raises on text input.
- Best-effort: tiktoken failures degrade to the heuristic, never crash a
  tool call.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class TokenCounter(Protocol):
    """Count tokens in a text string.

    Implementations must be total (never raise on valid str input) and
    deterministic for the same text + configured model.
    """

    @property
    def name(self) -> str:
        """Short identifier for reports (e.g. 'tiktoken:gpt-4o', 'heuristic')."""
        ...

    def count(self, text: str) -> int:
        """Return the token count of ``text`` (>= 0)."""
        ...


class HeuristicCounter:
    """Dependency-free estimate: ~4 chars per token.

    Same heuristic as ``AutoCompact._heuristic_count``. Good enough for
    relative comparisons (before/after token audits) and threshold checks;
    absolute values run ~±20% vs a real tokenizer.
    """

    name = "heuristic"

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)


class TiktokenCounter:
    """Exact tokenizer counter for OpenAI-family models.

    Encoding is selected by model name and cached on the instance. Unknown
    models fall back to ``cl100k_base`` (the GPT-4/4o family encoding), which
    is a close approximation for most modern chat tokenizers. The chosen
    encoding is exposed via :attr:`name` so reports can标注 the basis.
    """

    def __init__(self, model: str | None = None) -> None:
        import tiktoken  # local import: keeps import-failure isolated

        self._model = model
        try:
            self._enc = tiktoken.encoding_for_model(model) if model else None
        except (KeyError, ValueError):
            # Unknown model name — tiktoken can't map it. Fall back below.
            self._enc = None
        if self._enc is None:
            self._enc = tiktoken.get_encoding("cl100k_base")
            self._basis = "cl100k_base"
        else:
            self._basis = model or "cl100k_base"

    @property
    def name(self) -> str:
        return f"tiktoken:{self._basis}"

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._enc.encode(text, disallowed_special=()))


# ── process-level singleton ────────────────────────────────────────────

_counter: TokenCounter | None = None


def _resolve_default_counter() -> TokenCounter:
    """Build the default counter from env, degrading to heuristic on failure."""
    model = (
        os.environ.get("HARNESS_TOKENIZER_MODEL", "").strip()
        or os.environ.get("HARNESS_MODEL", "").strip()
        or None
    )
    try:
        return TiktokenCounter(model)
    except Exception as e:  # import error, encoding load failure, etc.
        logger.warning(
            "tiktoken unavailable (%s); falling back to HeuristicCounter for "
            "tool-output measurement", e,
        )
        return HeuristicCounter()


def get_token_counter() -> TokenCounter:
    """Return the process-level token counter (lazy singleton).

    Override for tests or custom tokenizers via :func:`set_token_counter`.
    """
    global _counter
    if _counter is None:
        _counter = _resolve_default_counter()
    return _counter


def set_token_counter(counter: TokenCounter | None) -> None:
    """Override (or reset, with ``None``) the process-level counter.

    Tests use this to inject a deterministic counter or force the
    heuristic fallback without manipulating imports.
    """
    global _counter
    _counter = counter
