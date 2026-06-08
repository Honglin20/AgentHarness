"""BatchFanIn — subscribes to N Bus instances, merges events into one queue.

Used by the batch WS endpoint to deliver events from all runs in a benchmark
through a single WebSocket connection.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Any

from harness.extensions.bus import Bus

logger = logging.getLogger(__name__)


class BatchFanIn:
    """Fan-in: subscribes to N Bus instances, merges events into one queue.

    Lifecycle:
        fan_in = BatchFanIn()
        await fan_in.start(batch_id, repo)
        # consumer reads from fan_in.queue
        await fan_in.stop()
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscriptions: list[tuple[str, str, Bus]] = []  # (sub_id, wid, bus)
        self._tasks: list[asyncio.Task] = []
        self._stopped = False
        self._total_runs = 0
        self._completed_runs = 0
        self._batch_id: str = ""
        self._completion_lock = asyncio.Lock()  # Protect batch.completed emission
        self._completion_emitted = False  # Track if batch.completed was already sent

    async def start(self, batch_id: str, repo: Any) -> None:
        """Subscribe to all buses in the batch. Replay ring buffers."""
        from server.repository import get_repository

        batch = repo.get_batch(batch_id)
        if not batch:
            raise ValueError(f"Batch {batch_id} not found")

        self._batch_id = batch_id
        runs = batch.get("runs", {})
        self._total_runs = len(runs)
        self._completed_runs = 0

        for wid, meta in runs.items():
            data = repo.get(wid)
            bus = data.get("event_bus") if data else None
            if not bus:
                # Already completed — count it
                status = meta.get("status", "")
                if status in ("completed", "failed"):
                    self._completed_runs += 1
                continue

            sub_id, queue = await bus.subscribe()
            self._subscriptions.append((sub_id, wid, bus))
            task = asyncio.create_task(self._forward(wid, queue))
            self._tasks.append(task)

        self._stopped = False

        # If all runs were already completed, emit batch.completed immediately
        if self._total_runs > 0 and self._completed_runs >= self._total_runs:
            await self._emit_batch_completed()

    async def stop(self) -> None:
        """Unsubscribe from all buses, cancel forwarding tasks."""
        self._stopped = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        for sub_id, _wid, bus in self._subscriptions:
            try:
                await bus.unsubscribe(sub_id)
            except Exception:
                logger.warning(
                    "Failed to unsubscribe %s from bus (workflow %s)",
                    sub_id, _wid, exc_info=True,
                )
        self._subscriptions.clear()
        self._tasks.clear()

    async def _forward(self, workflow_id: str, source: asyncio.Queue) -> None:
        """Forward events from a Bus queue to the merged queue."""
        try:
            while not self._stopped:
                event = await source.get()
                payload = event.get("payload", {})
                # Ensure workflow_id is present
                if "workflow_id" not in payload:
                    payload["workflow_id"] = workflow_id
                    event["payload"] = payload
                await self.queue.put(event)

                # Track completion
                evt_type = event.get("type", "")
                if evt_type in ("workflow.completed", "workflow.error"):
                    self._completed_runs += 1
                    if self._completed_runs >= self._total_runs:
                        await self._emit_batch_completed()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"Forward error for {workflow_id}")

    async def _emit_batch_completed(self) -> None:
        """Inject batch.completed synthetic event (only once)."""
        async with self._completion_lock:
            if self._completion_emitted:
                return
            self._completion_emitted = True

        self.queue.put_nowait({
            "type": "batch.completed",
            "ts": _time.time(),
            "payload": {
                "batch_id": self._batch_id,
                "total": self._total_runs,
                "completed": self._completed_runs,
            },
        })
