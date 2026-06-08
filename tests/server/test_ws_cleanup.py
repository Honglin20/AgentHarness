"""Verify background forward tasks are cancelled on disconnect."""
import asyncio

import pytest

from server.ws_handler import get_connection_manager


@pytest.mark.asyncio
async def test_disconnect_cancels_forward_task():
    """When a WS disconnects, its background forward task should be cancelled."""
    mgr = get_connection_manager()

    # Simulate a connection + background task. Real ConnectionManager stores
    # forward tasks in `_tasks` keyed by sub_id (see ws_handler.connect()).
    sub_id = "test-sub-cleanup-1"

    async def long_running():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            raise

    mgr._tasks[sub_id] = asyncio.create_task(long_running())

    # Disconnect is async and takes an event_bus. Pass a dummy bus —
    # unsubscribe() is the only method called on it, and it must be awaitable.
    class _DummyBus:
        async def unsubscribe(self, sid):
            return None

    await mgr.disconnect(sub_id, _DummyBus())

    # Yield to the loop so the CancelledError propagates into the task.
    await asyncio.sleep(0)

    # Task removed from registry ...
    assert sub_id not in mgr._tasks, f"Task for {sub_id} not removed from _tasks"
    # ... and the underlying task was actually cancelled.
    task = mgr._tasks.get(sub_id)
    assert task is None


@pytest.mark.asyncio
async def test_disconnect_handles_missing_task_gracefully():
    """If disconnect is called for a sub_id with no task, no error."""
    mgr = get_connection_manager()

    class _DummyBus:
        async def unsubscribe(self, sid):
            return None

    # Should not raise even though neither the connection nor task exists.
    await mgr.disconnect("never-existed-sub-id", _DummyBus())
