"""LLM error classification + retry policy.

Wraps ``executor.run()`` to retry on transient failures (429 / 5xx / network
jitter / stream truncation) and emit observable events so the UI can surface
"retrying (2/3): rate_limit" status. Final failure raises — node_factory's
``except Exception`` keeps its role as the safety net (emits ``node.failed``).

Design decisions (see PR-D plan):
- Retry scope: the WHOLE ``agent.iter()`` call. Pydantic AI's state machine
  does not support replaying a single step (the ``_next_node`` is set by the
  node stream's completion; re-driving a failed step breaks message_history
  idempotency). Caller passes a fresh ``run_fn`` callable that constructs a
  new iter() each attempt.
- JSONDecodeError one-shot counter lives on the policy INSTANCE so each
  ``execute_with_retry`` call (one per node_func invocation) gets its own
  budget. ``LLMRetryPolicy`` MUST be constructed fresh inside
  ``execute_with_retry``, not shared globally.
- ModelHTTPError does not expose response headers; Retry-After is parsed from
  ``body`` via multiple key paths (OpenAI / Anthropic / DeepSeek all differ).
  Miss → fall back to exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

import httpx

logger = logging.getLogger(__name__)


RetryCategory = Literal[
    "rate_limit",         # 429
    "server_error",       # 5xx
    "network_timeout",    # httpx.TimeoutException
    "network_error",      # httpx.NetworkError
    "stream_truncated",   # json.JSONDecodeError (likely truncated chunk)
    "client_error",       # other 4xx — do NOT retry (auth/param mistakes)
    "usage_exceeded",     # UsageLimitExceeded — graceful exit, do NOT retry
    "unknown",
]


@dataclass
class RetryDecision:
    """Outcome of classifying an exception."""

    should_retry: bool
    delay_s: float
    reason: str
    category: RetryCategory
    retry_after_s: float | None = None  # populated only when parsed from 429 body


# Exponential backoff schedules (seconds) keyed by category. Indexed by
# attempt (1-based). The schedule is intentionally short — this is for
# transient network/LLM-provider blips, not for sustained outages.
_BACKOFF: dict[str, list[float]] = {
    "rate_limit": [2.0, 4.0, 8.0, 16.0, 32.0, 60.0],   # base 2s, cap 60s
    "server_error": [1.0, 2.0, 4.0],
    "network_timeout": [2.0, 4.0, 8.0],
    "network_error": [1.0, 2.0, 4.0],
}


def _backoff(category: RetryCategory, attempt: int) -> float:
    schedule = _BACKOFF.get(category, [1.0, 2.0, 4.0])
    if attempt - 1 < len(schedule):
        return schedule[attempt - 1]
    return schedule[-1]  # cap at last entry


def _parse_retry_after(body: Any) -> float | None:
    """Best-effort: dig Retry-After out of ModelHTTPError.body.

    Different providers put it in different places:
      - OpenAI:        body['error']['headers']['retry-after'] (often a list like ['5'])
      - Anthropic:     body['error']['retry_after'] (string seconds)
      - DeepSeek/etc:  body['retry_after'] (top-level)
      - RFC style:     numeric seconds as int/str

    Returns None if nothing parseable is found — caller falls back to exp backoff.
    """
    if not isinstance(body, dict):
        return None

    candidates: list[Any] = []

    def _maybe_collect(key: str, value: Any) -> None:
        lk = key.lower().replace("-", "_")
        if lk in ("retry_after", "retryafter"):
            # value may be scalar OR list of scalars (OpenAI headers style)
            if isinstance(value, (list, tuple)):
                candidates.extend(value)
            else:
                candidates.append(value)

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _maybe_collect(str(k), v)
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(body)

    for raw in candidates:
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
        if isinstance(raw, str):
            try:
                v = float(raw)
                if v > 0:
                    return v
            except ValueError:
                pass  # intentional silent fallback — unparseable Retry-After string, try next candidate

    return None


class LLMRetryPolicy:
    """Classify LLM-related exceptions into retry decisions.

    Per-instance state is intentional: the JSONDecodeError one-shot counter
    must reset for each ``execute_with_retry`` invocation. Construct a fresh
    policy inside ``execute_with_retry``; do NOT share across calls.
    """

    def __init__(self, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        # One-shot guard: stream truncation is often transient but rarely
        # repeats on immediate retry; give it exactly one retry, then stop.
        self._json_decode_retries_used = 0

    def classify(self, exc: BaseException, attempt: int = 1) -> RetryDecision:
        # Lazy imports so the module loads cleanly even if pydantic_ai is
        # mid-upgrade (and so test code can monkeypatch easily).
        from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

        # 1) Usage limit — graceful exit, never retry
        if isinstance(exc, UsageLimitExceeded):
            return RetryDecision(
                should_retry=False,
                delay_s=0.0,
                reason=f"usage limit exceeded: {exc}",
                category="usage_exceeded",
            )

        # 2) Model HTTP error — split by status code
        if isinstance(exc, ModelHTTPError):
            status = getattr(exc, "status_code", 0) or 0
            if status == 429:
                retry_after = _parse_retry_after(getattr(exc, "body", None))
                if retry_after is not None:
                    return RetryDecision(
                        should_retry=True,
                        delay_s=min(retry_after, 60.0),
                        reason=f"rate limited (HTTP 429), server asked to wait {retry_after}s",
                        category="rate_limit",
                        retry_after_s=retry_after,
                    )
                delay = _backoff("rate_limit", attempt)
                return RetryDecision(
                    should_retry=True,
                    delay_s=delay,
                    reason=f"rate limited (HTTP 429), no Retry-After, backing off {delay}s",
                    category="rate_limit",
                )
            if 500 <= status < 600:
                delay = _backoff("server_error", attempt)
                return RetryDecision(
                    should_retry=True,
                    delay_s=delay,
                    reason=f"server error (HTTP {status}), backing off {delay}s",
                    category="server_error",
                )
            if 400 <= status < 500:
                return RetryDecision(
                    should_retry=False,
                    delay_s=0.0,
                    reason=f"client error (HTTP {status}) — not retryable",
                    category="client_error",
                )
            return RetryDecision(
                should_retry=False,
                delay_s=0.0,
                reason=f"unexpected HTTP status {status}",
                category="unknown",
            )

        # 3) httpx transport errors
        if isinstance(exc, httpx.TimeoutException):
            delay = _backoff("network_timeout", attempt)
            return RetryDecision(
                should_retry=True,
                delay_s=delay,
                reason=f"network timeout ({type(exc).__name__}), retrying in {delay}s",
                category="network_timeout",
            )
        if isinstance(exc, httpx.NetworkError):
            delay = _backoff("network_error", attempt)
            return RetryDecision(
                should_retry=True,
                delay_s=delay,
                reason=f"network error ({type(exc).__name__}), retrying in {delay}s",
                category="network_error",
            )

        # 4) Stream truncation — one shot only
        if isinstance(exc, json.JSONDecodeError):
            if self._json_decode_retries_used >= 1:
                return RetryDecision(
                    should_retry=False,
                    delay_s=0.0,
                    reason=f"stream truncated (JSON parse failed at line {exc.lineno} col {exc.colno}) — one-shot retry already used",
                    category="stream_truncated",
                )
            self._json_decode_retries_used += 1
            return RetryDecision(
                should_retry=True,
                delay_s=0.0,
                reason=f"stream truncated (JSON parse failed at line {exc.lineno} col {exc.colno}), retrying once",
                category="stream_truncated",
            )

        # 5) Unknown — never retry (fail loud, surface to user)
        return RetryDecision(
            should_retry=False,
            delay_s=0.0,
            reason=f"unclassified error ({type(exc).__name__}): {exc}",
            category="unknown",
        )


async def execute_with_retry(
    run_fn: Callable[[], Awaitable[Any]],
    *,
    bus: Any | None,
    workflow_id: str,
    node_id: str,
    agent_name: str,
    max_attempts: int = 3,
) -> Any:
    """Run ``run_fn`` with retry policy; emit observable events on each attempt.

    Args:
        run_fn: zero-arg async callable, typically ``lambda: executor.run(context)``.
            MUST construct a fresh ``agent.iter()`` each call (retry replays
            the whole iter — Pydantic AI does not support single-step retry).
        bus: Bus instance (or None — emits become no-ops).
        workflow_id / node_id / agent_name: routing context for emitted events.
        max_attempts: total tries including the first; default 3 = 1 try + 2 retries.

    Events emitted (all via safe_emit, auto-routed to critical via whitelist):
        - ``agent.retry_attempted``: after a failed attempt that will be retried
        - ``agent.failed_with_classified_reason``: after final attempt fails

    Behavior:
        - On final failure: re-raises the original exception. node_factory's
          ``except Exception`` (node_factory.py:602) catches it and emits
          ``node.failed`` for backwards compat.
    """
    from harness.extensions.bus import safe_emit

    # IMPORTANT: fresh policy per call so the JSONDecodeError one-shot counter
    # resets and previous-attempt state doesn't leak.
    policy = LLMRetryPolicy(max_attempts=max_attempts)

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await run_fn()
        except BaseException as exc:  # noqa: BLE001 — broad on purpose, classify decides
            # KeyboardInterrupt / CancelledError must propagate even though
            # they're BaseException — don't swallow cancellation.
            if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
                raise

            last_exc = exc
            decision = policy.classify(exc, attempt=attempt)

            will_retry = decision.should_retry and attempt < max_attempts

            if will_retry:
                safe_emit(bus, "agent.retry_attempted", {
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "agent_name": agent_name,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "category": decision.category,
                    "reason": decision.reason,
                    "delay_s": decision.delay_s,
                    "retry_after_s": decision.retry_after_s,
                })
                logger.info(
                    "agent.retry_attempted wf=%s node=%s attempt=%d/%d category=%s delay=%.2fs",
                    workflow_id, node_id, attempt, max_attempts,
                    decision.category, decision.delay_s,
                )
                if decision.delay_s > 0:
                    await asyncio.sleep(decision.delay_s)
                continue

            # Final attempt OR decision said "don't retry"
            safe_emit(bus, "agent.failed_with_classified_reason", {
                "workflow_id": workflow_id,
                "node_id": node_id,
                "agent_name": agent_name,
                "category": decision.category,
                "reason": decision.reason,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "attempts_used": attempt,
                "max_attempts": max_attempts,
            })
            logger.warning(
                "agent.failed_with_classified_reason wf=%s node=%s category=%s reason=%s",
                workflow_id, node_id, decision.category, decision.reason,
            )
            raise
