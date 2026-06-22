"""End-to-end tests for launch_task + wait_for_tasks + list/cancel.

Verifies the task lifecycle contract:
  - launch_task returns task_id immediately, registers in TaskRegistry
  - wait_for_tasks blocks until terminal state
  - task.* events emit with correct priority (critical for terminal, normal for heartbeat)
  - timeout_ms=0 default means "never kill" — task runs to natural completion
  - timeout_ms>0 still works as opt-in safety net
  - Failure path: exit_code surfaces in summary
  - Fan-out: N parallel tasks complete in ~max(N), not sum(N)
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai import RunContext

from harness.extensions.bus import Bus, CRITICAL_EVENT_TYPES
from harness.tools.deps import AgentDeps
from harness.tools.launch_task import LaunchTaskToolFactory
from harness.tools.task_registry import (
    TERMINAL_STATUSES,
    clear_registry,
    get_task_registry,
)
from harness.tools.task_wait import (
    CancelTaskToolFactory,
    ListTasksToolFactory,
    WaitForTasksToolFactory,
)


def _make_ctx(
    workdir: str = ".",
    agent_name: str = "test",
    workflow_id: str = "wf_test",
) -> RunContext[AgentDeps]:
    deps = AgentDeps(workdir=workdir, agent_name=agent_name, workflow_id=workflow_id)
    return RunContext(deps=deps, model=None, usage=None, prompt=None)


@pytest.fixture(autouse=True)
def _isolate_registry(monkeypatch):
    """Each test gets a fresh TaskRegistry.

    Tests that need the server.repository lookup (for event emission) should
    monkeypatch get_repository to return a fake bus.
    """
    # Reset all registries before and after each test
    from harness.tools import task_registry as mod

    with mod._registries_lock:
        mod._registries.clear()
    yield
    with mod._registries_lock:
        mod._registries.clear()


# ──────────────────────────────────────────────────────────────────────
# V1: short task (smoke) — launch + wait completes
# ──────────────────────────────────────────────────────────────────────


class TestLaunchWaitShort:
    def test_launch_returns_task_id_immediately(self, tmp_path: Path):
        factory = LaunchTaskToolFactory()
        tool = factory.create()
        ctx = _make_ctx(workdir=str(tmp_path))

        start = time.monotonic()
        result = tool.function(ctx, command="sleep 1; echo hi", description="sleep 1s")
        elapsed = time.monotonic() - start

        assert elapsed < 1.5, f"launch_task should return immediately, took {elapsed}s"
        assert "task_id: bg_" in result
        # task_id should be parseable and registered
        task_id = result.split("task_id: ", 1)[1].split("\n")[0].strip()
        registry = get_task_registry("wf_test")
        assert registry.get(task_id) is not None
        assert registry.get(task_id).status == "running"

    @pytest.mark.asyncio
    async def test_launch_wait_short_completes(self, tmp_path: Path):
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        launch_result = launch.function(
            ctx, command="sleep 1; echo hi", description="sleep 1s"
        )
        task_id = launch_result.split("task_id: ", 1)[1].split("\n")[0].strip()

        wait_result = await wait.function(ctx, task_ids=[task_id])

        assert "status=completed" in wait_result
        assert "exit=0" in wait_result
        registry = get_task_registry("wf_test")
        assert registry.get(task_id).status == "completed"


# ──────────────────────────────────────────────────────────────────────
# V2: opt-in hard timeout (safety net)
# ──────────────────────────────────────────────────────────────────────


class TestOptInTimeout:
    @pytest.mark.asyncio
    async def test_explicit_timeout_kills_task(self, tmp_path: Path):
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        # timeout_ms=1000 (1s) + sleep 30s → should be killed as timeout
        launch_result = launch.function(
            ctx,
            command="sleep 30",
            description="sleep 30s",
            timeout_ms=1000,
        )
        task_id = launch_result.split("task_id: ", 1)[1].split("\n")[0].strip()

        wait_result = await wait.function(ctx, task_ids=[task_id])

        assert "status=timeout" in wait_result
        registry = get_task_registry("wf_test")
        assert registry.get(task_id).status == "timeout"


# ──────────────────────────────────────────────────────────────────────
# V3: failure path — exit_code surfaces in summary
# ──────────────────────────────────────────────────────────────────────


class TestFailurePath:
    @pytest.mark.asyncio
    async def test_nonzero_exit_marked_failed(self, tmp_path: Path):
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        launch_result = launch.function(
            ctx, command="exit 7", description="exit with code 7"
        )
        task_id = launch_result.split("task_id: ", 1)[1].split("\n")[0].strip()

        wait_result = await wait.function(ctx, task_ids=[task_id])

        assert "status=failed" in wait_result
        assert "exit=7" in wait_result
        registry = get_task_registry("wf_test")
        assert registry.get(task_id).status == "failed"
        assert registry.get(task_id).exit_code == 7


# ──────────────────────────────────────────────────────────────────────
# V4: fan-out — N parallel tasks complete in ~max(N), not sum(N)
# ──────────────────────────────────────────────────────────────────────


class TestFanOut:
    @pytest.mark.asyncio
    async def test_three_parallel_tasks_run_concurrently(self, tmp_path: Path):
        """3 × sleep 2 should complete in ~2s, not ~6s."""
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        task_ids = []
        for _ in range(3):
            r = launch.function(ctx, command="sleep 2", description="sleep 2s")
            tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()
            task_ids.append(tid)

        start = time.monotonic()
        wait_result = await wait.function(ctx, task_ids=task_ids)
        elapsed = time.monotonic() - start

        # All should be completed
        assert wait_result.count("status=completed") == 3
        # Total time should be well under sequential (6s). Allow generous
        # overhead for thread spawn + polling.
        assert elapsed < 4.5, (
            f"Fan-out should be concurrent (~2s), took {elapsed:.1f}s — "
            "tasks may be running serially."
        )


# ──────────────────────────────────────────────────────────────────────
# V5: event priority — terminal events critical, heartbeat normal
# ──────────────────────────────────────────────────────────────────────


class TestEventPriority:
    def test_task_events_in_critical_whitelist(self):
        # Sanity: the CRITICAL_EVENT_TYPES whitelist includes task lifecycle
        for evt in (
            "task.submitted",
            "task.running",
            "task.completed",
            "task.failed",
            "task.timeout",
            "task.cancelled",
        ):
            assert evt in CRITICAL_EVENT_TYPES, (
                f"{evt} must be in CRITICAL_EVENT_TYPES — losing it would "
                "stick a DAG blocked on wait_for_tasks forever."
            )

    def test_heartbeat_not_in_critical_whitelist(self):
        # Heartbeat is intentionally normal — missing one is harmless (next
        # heartbeat covers it), and critical priority would grow the buffer
        # unboundedly during long training.
        assert "task.heartbeat" not in CRITICAL_EVENT_TYPES

    @pytest.mark.asyncio
    async def test_terminal_event_emitted_with_critical(self, tmp_path: Path):
        """task.completed should reach bus with priority='critical'."""
        bus = Bus()
        captured: list[tuple[str, dict, str]] = []  # (type, payload, priority)

        def _capture(event_type, payload, *, priority=None):
            resolved = priority or (
                "critical" if event_type in CRITICAL_EVENT_TYPES else "normal"
            )
            captured.append((event_type, payload, resolved))

        bus.emit = _capture  # type: ignore

        # Wire up the server.repository lookup to return our bus
        import server.repository as repo_mod

        class _FakeRepo:
            def get(self, wid):
                return {"event_bus": bus}

        with patch.object(repo_mod, "get_repository", return_value=_FakeRepo()):
            launch = LaunchTaskToolFactory().create()
            wait = WaitForTasksToolFactory().create()
            ctx = _make_ctx(workdir=str(tmp_path))

            r = launch.function(ctx, command="echo done", description="quick echo")
            tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()
            await wait.function(ctx, task_ids=[tid])

        # Wait briefly for monitor thread to fire completion event
        for _ in range(20):
            if any(t == "task.completed" for t, _, _ in captured):
                break
            await asyncio.sleep(0.05)

        types_seen = {t for t, _, _ in captured}
        assert "task.submitted" in types_seen, f"got: {types_seen}"
        assert "task.completed" in types_seen, f"got: {types_seen}"
        # All task.* events should resolve to critical
        for evt_type, _, prio in captured:
            if evt_type.startswith("task.") and evt_type != "task.heartbeat":
                assert prio == "critical", f"{evt_type} was {prio}, expected critical"


# ──────────────────────────────────────────────────────────────────────
# V6: heartbeat during long wait
# ──────────────────────────────────────────────────────────────────────


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_fires_for_long_running_task(self, tmp_path: Path):
        """Task running >30s should emit at least one task.heartbeat."""
        # Use a shorter heartbeat interval via direct patching
        from harness.tools import task_wait as mod

        # Patch HEARTBEAT_INTERVAL_S down to 0.5s so test runs fast
        original = mod.HEARTBEAT_INTERVAL_S
        mod.HEARTBEAT_INTERVAL_S = 0.5
        try:
            bus = Bus()
            captured: list[tuple[str, dict]] = []

            def _capture(event_type, payload, *, priority=None):
                captured.append((event_type, payload))

            bus.emit = _capture  # type: ignore

            import server.repository as repo_mod

            class _FakeRepo:
                def get(self, wid):
                    return {"event_bus": bus}

            with patch.object(repo_mod, "get_repository", return_value=_FakeRepo()):
                launch = LaunchTaskToolFactory().create()
                wait = WaitForTasksToolFactory().create()
                ctx = _make_ctx(workdir=str(tmp_path))

                r = launch.function(
                    ctx, command="sleep 2", description="sleep 2s"
                )
                tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()
                await wait.function(ctx, task_ids=[tid], poll_interval_ms=100)

            heartbeats = [p for t, p in captured if t == "task.heartbeat"]
            assert len(heartbeats) >= 2, (
                f"expected >=2 heartbeats during 2s wait, got {len(heartbeats)}"
            )
            # Verify payload shape
            for payload in heartbeats:
                assert "task_id" in payload
                assert "elapsed_sec" in payload
                assert "output_tail" in payload
        finally:
            mod.HEARTBEAT_INTERVAL_S = original


# ──────────────────────────────────────────────────────────────────────
# V8: default no-timeout — task runs to natural completion
# ──────────────────────────────────────────────────────────────────────


class TestDefaultNoTimeout:
    @pytest.mark.asyncio
    async def test_default_timeout_zero_waits_for_completion(self, tmp_path: Path):
        """Default launch_task(timeout_ms=0) lets task finish naturally."""
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        # Don't pass timeout_ms — default should be 0 = never kill
        r = launch.function(
            ctx, command="sleep 2; echo done", description="sleep 2s then done"
        )
        tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()

        # Sanity: task record shows timeout_ms=0
        registry = get_task_registry("wf_test")
        assert registry.get(tid).timeout_ms == 0

        wait_result = await wait.function(ctx, task_ids=[tid])

        assert "status=completed" in wait_result, (
            f"Default no-timeout should let task complete naturally, got: {wait_result}"
        )
        assert registry.get(tid).status == "completed"


# ──────────────────────────────────────────────────────────────────────
# Supporting tools: list_tasks, cancel_task
# ──────────────────────────────────────────────────────────────────────


class TestListTasks:
    def test_list_empty(self, tmp_path: Path):
        list_tool = ListTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))
        result = list_tool.function(ctx)
        assert "no tasks" in result

    def test_list_shows_running_then_completed(self, tmp_path: Path):
        list_tool = ListTasksToolFactory().create()
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        # Launch a quick task
        r = launch.function(ctx, command="echo hi", description="quick echo")
        tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()

        # Should appear in list
        result = list_tool.function(ctx)
        assert tid in result
        assert "running" in result or "completed" in result

    @pytest.mark.asyncio
    async def test_filter_by_status(self, tmp_path: Path):
        list_tool = ListTasksToolFactory().create()
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        r = launch.function(ctx, command="echo hi", description="quick echo")
        tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()
        await wait.function(ctx, task_ids=[tid])

        # Filter for completed
        result = list_tool.function(ctx, status="completed")
        assert tid in result

        # Filter for running should be empty
        running_result = list_tool.function(ctx, status="running")
        assert "no tasks" in running_result


class TestCancelTask:
    @pytest.mark.asyncio
    async def test_cancel_unknown_task(self, tmp_path: Path):
        cancel_tool = CancelTaskToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))
        result = cancel_tool.function(ctx, task_id="bg_nonexistent")
        assert "Error" in result
        assert "unknown" in result

    @pytest.mark.asyncio
    async def test_cancel_running_task(self, tmp_path: Path):
        """cancel_task should kill the process and mark status=cancelled."""
        cancel_tool = CancelTaskToolFactory().create()
        launch = LaunchTaskToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        r = launch.function(ctx, command="sleep 30", description="sleep 30s")
        tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()

        result = cancel_tool.function(ctx, task_id=tid)
        assert "cancelled" in result

        registry = get_task_registry("wf_test")
        assert registry.get(tid).status == "cancelled"


# ──────────────────────────────────────────────────────────────────────
# Unknown task_id handling in wait_for_tasks
# ──────────────────────────────────────────────────────────────────────


class TestUnknownTaskId:
    @pytest.mark.asyncio
    async def test_unknown_task_id_surfaces_in_summary(self, tmp_path: Path):
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))
        result = await wait.function(ctx, task_ids=["bg_unknown"])
        assert "unknown task_ids" in result
        assert "bg_unknown" in result

    @pytest.mark.asyncio
    async def test_mixed_known_unknown(self, tmp_path: Path):
        """Mix of known + unknown task_ids: known one waits, unknown surfaces."""
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        r = launch.function(ctx, command="echo hi", description="quick echo")
        known_tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()

        result = await wait.function(
            ctx, task_ids=[known_tid, "bg_unknown"]
        )
        assert "unknown task_ids" in result
        assert "bg_unknown" in result
        assert known_tid in result
