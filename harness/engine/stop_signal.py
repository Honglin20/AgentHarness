"""Stop/regenerate signal management for workflow interruption.

Extracted from macro_graph.py to enable independent testing and reuse.

Responsibilities:
- Store/consume stop-and-regenerate signals per workflow
- TTL-based signal expiry (configurable via HARNESS_STOP_REGEN_TTL env var)
- Async guidance handshake: await_guidance / provide_guidance via asyncio.Event
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


def _get_stop_regen_ttl() -> int:
    """Read TTL from env, defaulting to 60s."""
    try:
        return int(os.environ.get("HARNESS_STOP_REGEN_TTL", "60"))
    except ValueError:
        return 60


class StopSignalManager:
    """Manages stop/regenerate signals for a single MacroGraphBuilder.

    Each MacroGraphBuilder owns one StopSignalManager instance. The manager
    tracks:
    - ``_pending``: pending stop/regenerate signals keyed by workflow_id
    - ``_guidance_events``: asyncio.Event per workflow_id for the guidance handshake
    - ``_guidance_values``: guidance text per workflow_id

    Thread-safety for ``_pending``:
    - Async writers (``store`` / ``store_and_wake``) use ``_lock`` (asyncio.Lock).
    - Sync readers (``has_pending`` / ``consume``) use ``_sync_lock``
      (threading.Lock). This closes the check-then-act race between reading
      ``_ts`` and popping ``_pending``, which a concurrent ``store`` could
      otherwise mutate mid-check.
    """

    def __init__(self, ttl_seconds: int | None = None):
        self._ttl = ttl_seconds if ttl_seconds is not None else _get_stop_regen_ttl()
        self._pending: dict[str, dict[str, str | float]] = {}
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        self._guidance_events: dict[str, asyncio.Event] = {}
        self._guidance_values: dict[str, str] = {}

    # ---- Signal store / query / consume ----

    async def store(
        self,
        workflow_id: str,
        agent_name: str,
        partial_output: str,
        user_guidance: str,
    ) -> None:
        """Store a stop/regenerate signal.

        If a guidance event exists for this workflow and user_guidance is
        non-empty, directly wake the waiter via provide_guidance instead of
        storing.
        """
        # If nodeFunc is already waiting for guidance, wake it up directly
        if (
            user_guidance.strip()
            and workflow_id in self._guidance_events
            and not self._guidance_events[workflow_id].is_set()
        ):
            await self.provide_guidance(workflow_id, user_guidance)
            return

        async with self._lock:
            with self._sync_lock:
                self._pending[workflow_id] = {
                    "agent_name": agent_name,
                    "partial_output": partial_output,
                    "user_guidance": user_guidance,
                    "_ts": time.time(),
                }
        logger.warning(
            "[DIAG-STOP-2] Signal stored: "
            "wf=%s agent=%s guidance=%r partial_len=%d",
            workflow_id, agent_name, user_guidance[:50], len(partial_output),
        )

    async def store_and_wake(
        self,
        workflow_id: str,
        agent_name: str,
        partial_output: str,
        user_guidance: str,
    ) -> None:
        """Store a signal and unconditionally wake a guidance waiter.

        Used by the module-level shim when guidance is provided alongside
        the stop request and a waiter may be listening.
        """
        async with self._lock:
            with self._sync_lock:
                self._pending[workflow_id] = {
                    "agent_name": agent_name,
                    "partial_output": partial_output,
                    "user_guidance": user_guidance,
                    "_ts": time.time(),
                }
        if user_guidance.strip():
            await self.provide_guidance(workflow_id, user_guidance)

    def has_pending(self, workflow_id: str, agent_name: str) -> bool:
        """Check if there's a pending signal for this workflow+agent.

        Also handles TTL expiry: if the signal is older than ``_ttl`` seconds,
        it is removed and False is returned.

        Holds ``_sync_lock`` across the check-then-act (read ``_ts`` + pop)
        so a concurrent ``store`` cannot mutate ``_pending`` mid-check.
        """
        with self._sync_lock:
            pending = self._pending.get(workflow_id)
            if pending is None:
                return False
            if time.time() - pending.get("_ts", 0) > self._ttl:
                self._pending.pop(workflow_id, None)
                return False
            return pending.get("agent_name") == agent_name

    def consume(self, workflow_id: str) -> dict[str, str] | None:
        """Consume and return the signal, or None if absent.

        This is a destructive read: the signal is removed after consumption.
        Holds ``_sync_lock`` to stay consistent with ``has_pending`` and the
        async writers.
        """
        with self._sync_lock:
            return self._pending.pop(workflow_id, None)

    # ---- Async guidance handshake ----

    async def await_guidance(self, workflow_id: str, timeout: float = 300.0) -> str:
        """Block until user provides guidance via provide_guidance().

        Returns the guidance string, or "" on timeout.
        Cleans up the event and guidance value after returning.
        """
        self._guidance_events[workflow_id] = asyncio.Event()
        try:
            await asyncio.wait_for(
                self._guidance_events[workflow_id].wait(), timeout=timeout
            )
        except asyncio.TimeoutError:
            pass  # intentional silent fallback — "" sentinel returned below signals "no guidance provided"
        guidance = self._guidance_values.pop(workflow_id, "")
        self._guidance_events.pop(workflow_id, None)
        return guidance

    async def provide_guidance(self, workflow_id: str, guidance: str) -> None:
        """Set guidance and wake up the waiting coroutine."""
        self._guidance_values[workflow_id] = guidance
        event = self._guidance_events.get(workflow_id)
        if event is not None:
            event.set()
        logger.warning(
            "[DIAG-GUIDANCE] provide_guidance: guidance=%r has_event=%s wf=%s",
            guidance[:50], event is not None, workflow_id,
        )

    # ---- Cleanup ----

    def clear(self, workflow_id: str) -> None:
        """Clear all signals and guidance state for a workflow."""
        with self._sync_lock:
            self._pending.pop(workflow_id, None)
        self._guidance_events.pop(workflow_id, None)
        self._guidance_values.pop(workflow_id, None)
