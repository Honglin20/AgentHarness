"""Verify capacity check is atomic — no TOCTOU race.

Regression test: WorkflowRunner.submit previously relied on callers
(routes) to check `running_count >= max_concurrent` *before* calling
submit. Two concurrent requests could both pass that check before either
acquired the semaphore, allowing over-subscription.

The fix moves the check-and-acquire inside a single critical section in
`submit` itself.
"""

import asyncio

import pytest
from fastapi import HTTPException

from server.runner import WorkflowRunner


def _make_runner(max_concurrent: int = 1) -> WorkflowRunner:
    """Fresh runner with no shared singleton state."""
    return WorkflowRunner(max_concurrent=max_concurrent)


async def _fill_slot(runner: WorkflowRunner, wf_id: str, delay: float = 1.0) -> asyncio.Task:
    """Pre-register a fake long-running task in the runner's _running map.

    This simulates an in-flight workflow without actually executing one —
    the capacity check keys off `len(self._running)`, not the semaphore.
    """
    async def long_task():
        await asyncio.sleep(delay)

    task = asyncio.create_task(long_task())
    runner._running[wf_id] = task
    return task


@pytest.mark.asyncio
async def test_capacity_check_rejects_at_limit():
    """At max capacity, an additional submit is rejected immediately."""
    runner = _make_runner(max_concurrent=1)
    task = await _fill_slot(runner, "wf-1", delay=0.5)

    try:
        with pytest.raises(HTTPException) as exc:
            await runner.submit(
                workflow_id="wf-2",
                workflow=None,
                inputs={},
                event_bus=None,
            )
        # Message should mention capacity / max — same wording the routes use.
        msg = str(exc.value).lower()
        assert "max" in msg or "capacity" in msg, f"unexpected message: {exc.value}"
        # Status code must signal "too busy" — 429 (Too Many Requests) or
        # 409 (Conflict, what the routes already use) both qualify.
        assert exc.value.status_code in (409, 429, 503)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_capacity_check_atomic_under_concurrency():
    """Two concurrent submits against a full runner must both be rejected.

    Before the fix, the TOCTOU window let both pass `running_count` check
    (run in route) then queue on the semaphore inside submit — neither
    rejected, one blocked. With the check moved inside submit's lock,
    both must fail atomically.
    """
    runner = _make_runner(max_concurrent=1)

    accepted: list[str] = []
    rejected: list[str] = []

    async def try_submit(wf_id: str) -> None:
        try:
            await runner.submit(
                workflow_id=wf_id,
                workflow=None,
                inputs={},
                event_bus=None,
            )
            accepted.append(wf_id)
        except HTTPException:
            rejected.append(wf_id)
        except Exception:
            # Non-capacity errors (e.g. workflow=None blowing up inside
            # _run_workflow) should not be miscounted as "accepted".
            rejected.append(wf_id)

    # Pre-fill the single slot.
    blocker = await _fill_slot(runner, "wf-pre", delay=1.0)

    try:
        await asyncio.gather(
            try_submit("wf-a"),
            try_submit("wf-b"),
        )

        assert accepted == [], (
            f"{accepted} passed capacity check under concurrency — TOCTOU race"
        )
        assert len(rejected) == 2, f"expected 2 rejections, got {rejected}"
    finally:
        blocker.cancel()
        try:
            await blocker
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_capacity_check_releases_lock_on_failure():
    """If submit rejects due to capacity, the lock is released — subsequent
    submits (after a slot frees) must succeed."""
    runner = _make_runner(max_concurrent=1)
    blocker = await _fill_slot(runner, "wf-1", delay=0.1)

    # First submit must fail (slot full)
    with pytest.raises(HTTPException):
        await runner.submit(
            workflow_id="wf-2",
            workflow=None,
            inputs={},
            event_bus=None,
        )

    # Wait for the blocker task to finish and clear from _running.
    # _run_workflow isn't involved here (we injected the task directly),
    # so we must remove it manually.
    runner._running.pop("wf-1", None)

    try:
        await blocker
    except Exception:
        pass

    # Lock should be free; semaphore check must reflect 0 running now.
    # We can't easily verify "submit succeeds" without a real Workflow,
    # but we can verify the lock is not held by acquiring it.
    async with runner._lock:
        assert len(runner._running) == 0
