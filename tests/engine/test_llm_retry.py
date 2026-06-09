"""Tests for harness.engine.llm_retry — LLM error classification + retry policy.

Covers:
- classify() correctness across all exception categories (429 with/without
  Retry-After, 5xx, 4xx, UsageLimitExceeded, httpx timeout/network, JSONDecodeError
  one-shot counter)
- execute_with_retry end-to-end: emit retry_attempted, emit failed_with_classified_reason,
  final raise, no-retry-on-usage-exceeded
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from harness.engine.llm_retry import (
    LLMRetryPolicy,
    RetryDecision,
    _parse_retry_after,
    execute_with_retry,
)


# ---------------------------------------------------------------------------
# _parse_retry_after — body shape variants
# ---------------------------------------------------------------------------

class TestParseRetryAfter:
    def test_openai_list_style_in_headers(self):
        # OpenAI shape: body['error']['headers']['retry-after'] = ['5']
        body = {"error": {"headers": {"retry-after": ["5"]}}}
        assert _parse_retry_after(body) == 5.0

    def test_anthropic_string_in_error(self):
        body = {"error": {"retry_after": "3.5"}}
        assert _parse_retry_after(body) == 3.5

    def test_deepseek_top_level(self):
        body = {"retry_after": 10}
        assert _parse_retry_after(body) == 10.0

    def test_int_value(self):
        body = {"retry_after": 7}
        assert _parse_retry_after(body) == 7.0

    def test_nested_deeper(self):
        body = {"foo": {"bar": {"retry-after": ["2"]}}}
        assert _parse_retry_after(body) == 2.0

    def test_no_retry_after_key(self):
        assert _parse_retry_after({"foo": "bar"}) is None

    def test_empty_dict(self):
        assert _parse_retry_after({}) is None

    def test_non_dict_body(self):
        assert _parse_retry_after("hello") is None
        assert _parse_retry_after(None) is None

    def test_invalid_string_value(self):
        # String that can't parse as float → skip, return None
        assert _parse_retry_after({"retry_after": "not-a-number"}) is None

    def test_negative_or_zero_ignored(self):
        # Edge case: server shouldn't return <=0, but be defensive
        assert _parse_retry_after({"retry_after": -5}) is None
        assert _parse_retry_after({"retry_after": 0}) is None


# ---------------------------------------------------------------------------
# LLMRetryPolicy.classify
# ---------------------------------------------------------------------------

class TestClassify:
    def _policy(self):
        return LLMRetryPolicy(max_attempts=3)

    def test_usage_limit_exceeded_no_retry(self):
        from pydantic_ai.exceptions import UsageLimitExceeded
        d = self._policy().classify(UsageLimitExceeded("request_limit of 50 exceeded"))
        assert d.should_retry is False
        assert d.category == "usage_exceeded"

    def test_model_http_429_with_retry_after(self):
        from pydantic_ai.exceptions import ModelHTTPError
        exc = ModelHTTPError(
            status_code=429, model_name="test",
            body={"error": {"headers": {"retry-after": ["5"]}}},
        )
        d = self._policy().classify(exc)
        assert d.should_retry is True
        assert d.category == "rate_limit"
        assert d.delay_s == 5.0
        assert d.retry_after_s == 5.0

    def test_model_http_429_without_retry_after_uses_backoff(self):
        from pydantic_ai.exceptions import ModelHTTPError
        exc = ModelHTTPError(status_code=429, model_name="test", body={})
        d = self._policy().classify(exc, attempt=1)
        assert d.should_retry is True
        assert d.category == "rate_limit"
        # attempt 1 → base 2s
        assert d.delay_s == 2.0
        assert d.retry_after_s is None

    def test_model_http_429_backoff_caps_at_60s(self):
        from pydantic_ai.exceptions import ModelHTTPError
        exc = ModelHTTPError(status_code=429, model_name="test", body={})
        # attempt 10 (way past schedule) → cap 60s
        d = self._policy().classify(exc, attempt=10)
        assert d.delay_s == 60.0

    def test_model_http_500_should_retry(self):
        from pydantic_ai.exceptions import ModelHTTPError
        exc = ModelHTTPError(status_code=503, model_name="test", body={})
        d = self._policy().classify(exc, attempt=1)
        assert d.should_retry is True
        assert d.category == "server_error"
        assert d.delay_s == 1.0  # first attempt → 1s

    def test_model_http_502_504_also_retry(self):
        from pydantic_ai.exceptions import ModelHTTPError
        for status in (500, 502, 503, 504):
            exc = ModelHTTPError(status_code=status, model_name="t", body={})
            d = self._policy().classify(exc)
            assert d.should_retry is True
            assert d.category == "server_error"

    def test_model_http_4xx_no_retry(self):
        from pydantic_ai.exceptions import ModelHTTPError
        for status in (400, 401, 403, 404, 422):
            exc = ModelHTTPError(status_code=status, model_name="t", body={})
            d = self._policy().classify(exc)
            assert d.should_retry is False
            assert d.category == "client_error"

    def test_httpx_timeout_retry(self):
        exc = httpx.ReadTimeout("timeout reading")
        d = self._policy().classify(exc, attempt=1)
        assert d.should_retry is True
        assert d.category == "network_timeout"
        assert d.delay_s == 2.0

    def test_httpx_network_error_retry(self):
        exc = httpx.ConnectError("connection refused")
        d = self._policy().classify(exc, attempt=1)
        assert d.should_retry is True
        assert d.category == "network_error"
        assert d.delay_s == 1.0

    def test_json_decode_error_one_shot(self):
        exc = json.JSONDecodeError("expecting value", '{"incomplete', 12)
        policy = self._policy()
        d1 = policy.classify(exc, attempt=1)
        assert d1.should_retry is True
        assert d1.category == "stream_truncated"
        assert d1.delay_s == 0.0
        # Second call — already used the one-shot
        d2 = policy.classify(exc, attempt=2)
        assert d2.should_retry is False
        assert d2.category == "stream_truncated"

    def test_json_decode_counter_resets_per_policy_instance(self):
        """Critical: the one-shot counter must NOT be shared across instances
        (otherwise two consecutive JSONDecodeError retries in different
        execute_with_retry calls would unfairly starve the second)."""
        exc = json.JSONDecodeError("expecting value", '{"incomplete', 12)
        p1 = self._policy()
        p1.classify(exc)  # use up the budget on p1
        p2 = self._policy()  # fresh policy → fresh budget
        d = p2.classify(exc)
        assert d.should_retry is True

    def test_unknown_exception_no_retry(self):
        d = self._policy().classify(ValueError("weird"))
        assert d.should_retry is False
        assert d.category == "unknown"


# ---------------------------------------------------------------------------
# execute_with_retry — end-to-end behavior
# ---------------------------------------------------------------------------

class TestExecuteWithRetry:
    @pytest.mark.asyncio
    async def test_success_first_try_no_events(self):
        bus = MagicMock()
        run_fn = AsyncMock(return_value="ok")
        result = await execute_with_retry(
            run_fn, bus=bus, workflow_id="w", node_id="n", agent_name="a",
        )
        assert result == "ok"
        # No retry/failed events emitted
        bus.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_then_success_emits_retry_attempted(self):
        """First attempt fails (5xx), second succeeds. Should emit one
        agent.retry_attempted event."""
        from pydantic_ai.exceptions import ModelHTTPError
        bus = MagicMock()
        # Patch asyncio.sleep so the test doesn't actually wait
        with patch("harness.engine.llm_retry.asyncio.sleep", new=AsyncMock()):
            run_fn = AsyncMock(
                side_effect=[
                    ModelHTTPError(status_code=503, model_name="t", body={}),
                    "ok",
                ]
            )
            result = await execute_with_retry(
                run_fn, bus=bus, workflow_id="w", node_id="n", agent_name="a",
                max_attempts=3,
            )
        assert result == "ok"
        assert run_fn.call_count == 2
        # One retry_attempted emit (between attempt 1 and 2)
        emits = [c.args for c in bus.emit.call_args_list]
        retry_emits = [e for e in emits if e[0] == "agent.retry_attempted"]
        assert len(retry_emits) == 1
        # Verify payload
        payload = retry_emits[0][1]
        assert payload["attempt"] == 1
        assert payload["max_attempts"] == 3
        assert payload["category"] == "server_error"

    @pytest.mark.asyncio
    async def test_exhaust_retries_emits_failed_with_classified_reason(self):
        """All 3 attempts fail with 5xx → emit 2 retry_attempted + 1 failed."""
        from pydantic_ai.exceptions import ModelHTTPError
        bus = MagicMock()
        with patch("harness.engine.llm_retry.asyncio.sleep", new=AsyncMock()):
            run_fn = AsyncMock(
                side_effect=ModelHTTPError(status_code=503, model_name="t", body={})
            )
            with pytest.raises(ModelHTTPError):
                await execute_with_retry(
                    run_fn, bus=bus, workflow_id="w", node_id="n", agent_name="a",
                    max_attempts=3,
                )
        assert run_fn.call_count == 3
        emits = [c.args for c in bus.emit.call_args_list]
        retry_emits = [e for e in emits if e[0] == "agent.retry_attempted"]
        failed_emits = [e for e in emits if e[0] == "agent.failed_with_classified_reason"]
        assert len(retry_emits) == 2  # attempt 1→2 and 2→3
        assert len(failed_emits) == 1
        # Verify failed payload
        payload = failed_emits[0][1]
        assert payload["category"] == "server_error"
        assert payload["attempts_used"] == 3

    @pytest.mark.asyncio
    async def test_usage_exceeded_no_retry_immediately_fails(self):
        """UsageLimitExceeded is graceful-exit, not retryable."""
        from pydantic_ai.exceptions import UsageLimitExceeded
        bus = MagicMock()
        run_fn = AsyncMock(side_effect=UsageLimitExceeded("request_limit of 200 exceeded"))
        with pytest.raises(UsageLimitExceeded):
            await execute_with_retry(
                run_fn, bus=bus, workflow_id="w", node_id="n", agent_name="a",
                max_attempts=3,
            )
        # run_fn called exactly once (no retries)
        assert run_fn.call_count == 1
        emits = [c.args for c in bus.emit.call_args_list]
        retry_emits = [e for e in emits if e[0] == "agent.retry_attempted"]
        failed_emits = [e for e in emits if e[0] == "agent.failed_with_classified_reason"]
        assert len(retry_emits) == 0
        assert len(failed_emits) == 1
        assert failed_emits[0][1]["category"] == "usage_exceeded"

    @pytest.mark.asyncio
    async def test_client_error_no_retry_immediately_fails(self):
        """4xx errors are not retried (auth/param mistakes won't fix themselves)."""
        from pydantic_ai.exceptions import ModelHTTPError
        bus = MagicMock()
        run_fn = AsyncMock(side_effect=ModelHTTPError(status_code=401, model_name="t", body={}))
        with pytest.raises(ModelHTTPError):
            await execute_with_retry(
                run_fn, bus=bus, workflow_id="w", node_id="n", agent_name="a",
                max_attempts=3,
            )
        assert run_fn.call_count == 1
        emits = [c.args for c in bus.emit.call_args_list]
        failed_emits = [e for e in emits if e[0] == "agent.failed_with_classified_reason"]
        assert len(failed_emits) == 1
        assert failed_emits[0][1]["category"] == "client_error"

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_propagates_no_retry(self):
        """KeyboardInterrupt must not be swallowed even though it's BaseException."""
        bus = MagicMock()
        run_fn = AsyncMock(side_effect=KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            await execute_with_retry(
                run_fn, bus=bus, workflow_id="w", node_id="n", agent_name="a",
            )
        # No events emitted
        bus.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_no_retry(self):
        """asyncio.CancelledError must propagate — don't swallow cancellation."""
        bus = MagicMock()
        run_fn = AsyncMock(side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await execute_with_retry(
                run_fn, bus=bus, workflow_id="w", node_id="n", agent_name="a",
            )
        bus.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_bus_none_emits_are_no_ops(self):
        """bus=None should not crash — emits silently no-op via safe_emit."""
        from pydantic_ai.exceptions import ModelHTTPError
        from harness.extensions.bus import safe_emit
        with patch("harness.engine.llm_retry.asyncio.sleep", new=AsyncMock()):
            run_fn = AsyncMock(
                side_effect=[
                    ModelHTTPError(status_code=503, model_name="t", body={}),
                    "ok",
                ]
            )
            # bus=None → safe_emit returns immediately
            result = await execute_with_retry(
                run_fn, bus=None, workflow_id="w", node_id="n", agent_name="a",
            )
        assert result == "ok"
        assert run_fn.call_count == 2
