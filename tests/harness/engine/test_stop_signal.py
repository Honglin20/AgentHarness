"""Tests for StopSignalManager — stop/regenerate signal management.

Extracted from macro_graph.py to enable independent testing and reuse.

Key behaviors tested:
1. store + consume round-trip
2. consume twice returns None (signal is consumed once)
3. has_pending checks by workflow_id + agent_name
4. TTL expiry: signals older than TTL are cleaned up
5. await_guidance + provide_guidance async handshake
6. clear removes all signals for a workflow
"""

import asyncio
import time

import pytest

from harness.engine.stop_signal import StopSignalManager


class TestStoreAndConsume:
    """Test store/consume round-trip."""

    @pytest.mark.asyncio
    async def test_store_and_consume(self):
        """Store a signal, then consume it — should get it back."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial output", "do better")

        result = mgr.consume("wf-1")
        assert result is not None
        assert result["agent_name"] == "agent_a"
        assert result["partial_output"] == "partial output"
        assert result["user_guidance"] == "do better"
        assert "_ts" in result

    @pytest.mark.asyncio
    async def test_consume_twice_returns_none(self):
        """Consuming a signal twice returns None the second time."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial", "guidance")

        first = mgr.consume("wf-1")
        assert first is not None

        second = mgr.consume("wf-1")
        assert second is None

    @pytest.mark.asyncio
    async def test_consume_nonexistent_returns_none(self):
        """Consuming a nonexistent workflow returns None."""
        mgr = StopSignalManager(ttl_seconds=60)
        assert mgr.consume("no-such-wf") is None


class TestHasPending:
    """Test has_pending checks."""

    @pytest.mark.asyncio
    async def test_has_pending_true(self):
        """has_pending returns True when signal exists for matching agent."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial", "guidance")

        assert mgr.has_pending("wf-1", "agent_a") is True

    @pytest.mark.asyncio
    async def test_has_pending_wrong_agent(self):
        """has_pending returns False when agent_name doesn't match."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial", "guidance")

        assert mgr.has_pending("wf-1", "agent_b") is False

    @pytest.mark.asyncio
    async def test_has_pending_wrong_workflow(self):
        """has_pending returns False when workflow_id doesn't exist."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial", "guidance")

        assert mgr.has_pending("wf-2", "agent_a") is False


class TestTTLExpiry:
    """Test TTL-based expiry of signals."""

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        """Signals older than TTL are expired and cleaned up."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial", "guidance")

        # Fresh signal should be detected
        assert mgr.has_pending("wf-1", "agent_a") is True

        # Manually backdate the timestamp to simulate expiry
        mgr._pending["wf-1"]["_ts"] = time.time() - 61

        # Should be expired
        assert mgr.has_pending("wf-1", "agent_a") is False
        # Signal should be cleaned up
        assert "wf-1" not in mgr._pending

    @pytest.mark.asyncio
    async def test_ttl_not_expired(self):
        """Signals within TTL are still valid."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial", "guidance")

        # Set timestamp to 30s ago — still within 60s TTL
        mgr._pending["wf-1"]["_ts"] = time.time() - 30

        assert mgr.has_pending("wf-1", "agent_a") is True


class TestAwaitGuidance:
    """Test the async guidance handshake."""

    @pytest.mark.asyncio
    async def test_await_guidance(self):
        """await_guidance blocks until provide_guidance is called."""
        mgr = StopSignalManager(ttl_seconds=60)
        mgr._guidance_events["wf-1"] = asyncio.Event()

        result = []

        async def waiter():
            guidance = await mgr.await_guidance("wf-1", timeout=5.0)
            result.append(guidance)

        async def provider():
            await asyncio.sleep(0.05)
            await mgr.provide_guidance("wf-1", "new direction")

        await asyncio.gather(waiter(), provider())

        assert result == ["new direction"]

    @pytest.mark.asyncio
    async def test_await_guidance_timeout(self):
        """await_guidance returns empty string on timeout."""
        mgr = StopSignalManager(ttl_seconds=60)
        mgr._guidance_events["wf-1"] = asyncio.Event()

        guidance = await mgr.await_guidance("wf-1", timeout=0.1)
        assert guidance == ""

    @pytest.mark.asyncio
    async def test_await_guidance_cleanup(self):
        """After await_guidance returns, event is cleaned up."""
        mgr = StopSignalManager(ttl_seconds=60)
        mgr._guidance_events["wf-1"] = asyncio.Event()

        async def waiter():
            return await mgr.await_guidance("wf-1", timeout=5.0)

        async def provider():
            await asyncio.sleep(0.01)
            await mgr.provide_guidance("wf-1", "go")

        await asyncio.gather(waiter(), provider())
        # Event should be cleaned up
        assert "wf-1" not in mgr._guidance_events

    @pytest.mark.asyncio
    async def test_provide_guidance_fires_event(self):
        """provide_guidance sets the guidance text and fires the event."""
        mgr = StopSignalManager(ttl_seconds=60)
        mgr._guidance_events["wf-1"] = asyncio.Event()

        await mgr.provide_guidance("wf-1", "use Chinese")

        assert mgr._guidance_values["wf-1"] == "use Chinese"
        assert mgr._guidance_events["wf-1"].is_set()

    @pytest.mark.asyncio
    async def test_provide_guidance_no_event_is_noop(self):
        """provide_guidance when no event exists just stores guidance."""
        mgr = StopSignalManager(ttl_seconds=60)

        # Should not raise
        await mgr.provide_guidance("wf-1", "some guidance")
        assert mgr._guidance_values["wf-1"] == "some guidance"


class TestClear:
    """Test clearing signals."""

    @pytest.mark.asyncio
    async def test_clear(self):
        """clear removes all signals for a workflow."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial", "guidance")

        assert mgr.has_pending("wf-1", "agent_a") is True

        mgr.clear("wf-1")

        assert mgr.has_pending("wf-1", "agent_a") is False
        assert mgr.consume("wf-1") is None

    def test_clear_nonexistent_is_noop(self):
        """Clearing a nonexistent workflow is a no-op."""
        mgr = StopSignalManager(ttl_seconds=60)
        # Should not raise
        mgr.clear("no-such-wf")

    @pytest.mark.asyncio
    async def test_clear_does_not_affect_other_workflows(self):
        """Clearing one workflow doesn't affect another."""
        mgr = StopSignalManager(ttl_seconds=60)
        await mgr.store("wf-1", "agent_a", "partial", "guidance")
        await mgr.store("wf-2", "agent_b", "partial", "guidance")

        mgr.clear("wf-1")

        assert mgr.has_pending("wf-1", "agent_a") is False
        assert mgr.has_pending("wf-2", "agent_b") is True


class TestRequestStopWithGuidance:
    """Test the request_stop_and_regenerate shortcut that wakes guidance."""

    @pytest.mark.asyncio
    async def test_request_with_guidance_wakes_waiter(self):
        """store with guidance wakes up a waiting await_guidance."""
        mgr = StopSignalManager(ttl_seconds=60)
        mgr._guidance_events["wf-1"] = asyncio.Event()

        result = []

        async def waiter():
            guidance = await mgr.await_guidance("wf-1", timeout=5.0)
            result.append(guidance)

        async def requester():
            await asyncio.sleep(0.05)
            # This should wake up the waiter because guidance is non-empty
            # and event is not yet set
            await mgr.store_and_wake("wf-1", "agent_a", "partial", "wake up!")

        await asyncio.gather(waiter(), requester())

        assert result == ["wake up!"]
