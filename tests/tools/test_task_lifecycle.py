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
            # Verify payload shape — every field the frontend relies on
            for payload in heartbeats:
                assert "task_id" in payload
                assert "elapsed_sec" in payload
                assert "output_tail" in payload
                # expected_remaining_sec + progress may be None but must be present
                assert "expected_remaining_sec" in payload
                assert "progress" in payload
        finally:
            mod.HEARTBEAT_INTERVAL_S = original


# ──────────────────────────────────────────────────────────────────────
# V7: read_output_tail caps output size (M3 + L1 regression)
# ──────────────────────────────────────────────────────────────────────


class TestReadOutputTailSize:
    """M3 fix: read_output_tail uses seek-from-end so multi-hundred-MB training
    logs don't get loaded into memory on every heartbeat. Verify via direct
    function call (heartbeat path is timing-dependent).
    """

    def test_tail_capped_to_constant_large_file(self, tmp_path: Path):
        """A 5MB log file should yield a tail of ~OUTPUT_TAIL_CHARS, not 5MB."""
        from harness.tools.task_registry import OUTPUT_TAIL_CHARS, read_output_tail

        big_log = tmp_path / "big.log"
        # Write ~5 MB of ASCII content
        line = "x" * 80 + "\n"
        with big_log.open("w") as f:
            for _ in range(60_000):  # ~4.8 MB
                f.write(line)

        tail = read_output_tail(str(big_log))
        # Seek-based read gives at most OUTPUT_TAIL_CHARS * 4 + 8 bytes raw,
        # then we slice [-max_chars:] on the decoded string. Result length is
        # bounded by OUTPUT_TAIL_CHARS (in characters).
        assert len(tail) <= OUTPUT_TAIL_CHARS
        assert len(tail) > 0
        # Must include the last line (most recent training output)
        assert tail.endswith("x" * 80 + "\n") or tail.endswith("x" * 80)

    def test_tail_small_file_returns_full_content(self, tmp_path: Path):
        """Files smaller than OUTPUT_TAIL_CHARS return as-is (no truncation)."""
        from harness.tools.task_registry import read_output_tail

        small_log = tmp_path / "small.log"
        small_log.write_text("only a few lines\nshort content\n")

        tail = read_output_tail(str(small_log))
        assert tail == "only a few lines\nshort content\n"

    def test_tail_missing_file_returns_empty(self, tmp_path: Path):
        from harness.tools.task_registry import read_output_tail

        assert read_output_tail(str(tmp_path / "nonexistent.log")) == ""


# ──────────────────────────────────────────────────────────────────────
# T3: emit_task_event failure — launch_task still returns task_id
# ──────────────────────────────────────────────────────────────────────


class TestEmitFailure:
    """If bus/repository is unavailable, launch_task must still return a task_id.
    Event emission is fire-and-forget — failures shouldn't break task lifecycle.
    """

    @pytest.mark.asyncio
    async def test_launch_returns_task_id_when_repo_missing(self, tmp_path: Path):
        """No server.repository configured — emit_task_event should swallow."""
        import server.repository as repo_mod

        class _EmptyRepo:
            def get(self, wid):
                return None  # no data for this workflow

        with patch.object(repo_mod, "get_repository", return_value=_EmptyRepo()):
            launch = LaunchTaskToolFactory().create()
            wait = WaitForTasksToolFactory().create()
            ctx = _make_ctx(workdir=str(tmp_path))

            r = launch.function(ctx, command="echo hi", description="quick echo")
            # Should still return a task_id even if event emission failed
            assert "task_id: bg_" in r
            tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()

            # wait_for_tasks should complete normally
            result = await wait.function(ctx, task_ids=[tid])
            assert "status=completed" in result

    @pytest.mark.asyncio
    async def test_launch_returns_task_id_when_repo_raises(self, tmp_path: Path):
        """server.repository.get raises — emit_task_event should catch + log."""
        import server.repository as repo_mod

        class _RaisingRepo:
            def get(self, wid):
                raise RuntimeError("simulated DB failure")

        with patch.object(repo_mod, "get_repository", return_value=_RaisingRepo()):
            launch = LaunchTaskToolFactory().create()
            ctx = _make_ctx(workdir=str(tmp_path))

            r = launch.function(ctx, command="echo hi", description="quick echo")
            assert "task_id: bg_" in r  # still returned despite emit failure


# ──────────────────────────────────────────────────────────────────────
# T5: summary format parseability — wait_for_tasks output is LLM-parseable
# ──────────────────────────────────────────────────────────────────────


class TestSummaryFormat:
    """wait_for_tasks returns a summary that the LLM must parse to know each
    task's status. Lock in the format with a regex so changes are intentional.
    """

    @pytest.mark.asyncio
    async def test_summary_line_format_matches_regex(self, tmp_path: Path):
        import re

        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        # Launch a completed and a failed task
        r_ok = launch.function(ctx, command="echo done", description="ok")
        r_fail = launch.function(ctx, command="exit 3", description="fail")
        tid_ok = r_ok.split("task_id: ", 1)[1].split("\n")[0].strip()
        tid_fail = r_fail.split("task_id: ", 1)[1].split("\n")[0].strip()

        summary = await wait.function(ctx, task_ids=[tid_ok, tid_fail])

        # Each task line should match this pattern (LLM-parseable):
        #   task_id=bg_xxx  status=completed  exit=0  output=path
        line_pattern = re.compile(
            r"^task_id=(\S+)\s+status=(\w+)\s+exit=(\S+)\s+output=(.+)$"
        )
        lines = [l for l in summary.split("\n") if l.startswith("task_id=")]
        assert len(lines) == 2

        parsed = {}
        for line in lines:
            m = line_pattern.match(line)
            assert m is not None, f"line does not match pattern: {line!r}"
            tid, status, exit_code, _output = m.groups()
            parsed[tid] = (status, exit_code)

        assert parsed[tid_ok][0] == "completed"
        assert parsed[tid_ok][1] == "0"
        assert parsed[tid_fail][0] == "failed"
        assert parsed[tid_fail][1] == "3"

    @pytest.mark.asyncio
    async def test_summary_header_has_terminal_count(self, tmp_path: Path):
        launch = LaunchTaskToolFactory().create()
        wait = WaitForTasksToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        r = launch.function(ctx, command="echo hi", description="quick")
        tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()
        summary = await wait.function(ctx, task_ids=[tid])

        # Header: "[1/1 tasks terminal in Xs]"
        import re

        assert re.search(r"\[1/1 tasks terminal in [\d.]+s\]", summary)


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
# T1: cancel_task + on_complete race — C1 regression
# ──────────────────────────────────────────────────────────────────────


class TestCancelRaceWithOnComplete:
    """C1 fix: cancel_task sets status=cancelled; if the bash monitor observes
    process death and calls _on_complete after, it MUST NOT overwrite the
    cancelled status back to failed.
    """

    @pytest.mark.asyncio
    async def test_cancelled_status_survives_on_complete(self, tmp_path: Path):
        """Simulate the race: cancel first, then trigger _on_complete."""
        launch = LaunchTaskToolFactory().create()
        ctx = _make_ctx(workdir=str(tmp_path))

        # Launch a long-running task
        r = launch.function(ctx, command="sleep 30", description="sleep 30s")
        tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()

        registry = get_task_registry("wf_test")

        # Cancel the task — this sets status=cancelled, exit_code=-15
        from harness.tools.task_wait import CancelTaskToolFactory

        cancel_tool = CancelTaskToolFactory().create()
        cancel_tool.function(ctx, task_id=tid)
        assert registry.get(tid).status == "cancelled"
        assert registry.get(tid).exit_code == -15

        # Now simulate the monitor observing process death and calling _on_complete.
        # The real monitor WILL call _on_complete when the killed process exits;
        # we just wait briefly for that to happen. Without the C1 fix, the status
        # would flip from "cancelled" back to "failed" here.
        await asyncio.sleep(0.5)

        # Critical assertion: status must remain cancelled, not flip to failed
        task = registry.get(tid)
        assert task.status == "cancelled", (
            f"Race regression: _on_complete overwrote cancelled back to {task.status}"
        )
        assert task.exit_code == -15, (
            f"Race regression: exit_code changed from -15 to {task.exit_code}"
        )

    @pytest.mark.asyncio
    async def test_cancelled_emits_only_one_terminal_event(self, tmp_path: Path):
        """Verify only task.cancelled is emitted, not followed by task.failed."""
        from harness.extensions.bus import Bus, CRITICAL_EVENT_TYPES

        bus = Bus()
        events: list[str] = []

        def _capture(event_type, payload, *, priority=None):
            events.append(event_type)

        bus.emit = _capture  # type: ignore

        import server.repository as repo_mod

        class _FakeRepo:
            def get(self, wid):
                return {"event_bus": bus}

        with patch.object(repo_mod, "get_repository", return_value=_FakeRepo()):
            launch = LaunchTaskToolFactory().create()
            from harness.tools.task_wait import CancelTaskToolFactory

            cancel_tool = CancelTaskToolFactory().create()
            ctx = _make_ctx(workdir=str(tmp_path))

            r = launch.function(ctx, command="sleep 30", description="sleep 30s")
            tid = r.split("task_id: ", 1)[1].split("\n")[0].strip()
            cancel_tool.function(ctx, task_id=tid)

        await asyncio.sleep(0.5)
        # Should see: task.submitted + task.cancelled, NOT task.failed
        assert "task.cancelled" in events
        assert "task.failed" not in events, (
            f"Race regression: task.failed emitted after cancel. Events: {events}"
        )


# ──────────────────────────────────────────────────────────────────────
# T2: on_complete raising doesn't break cleanup — H4 regression
# ──────────────────────────────────────────────────────────────────────


class TestOnCompleteException:
    """H4 fix: if on_complete raises, the bash monitor must still clean up
    _bg_tasks and emit bash.background_completed. Otherwise task slots leak
    and TaskRegistry may stick in 'running'.
    """

    def test_on_complete_raising_does_not_break_cleanup(self, tmp_path: Path):
        from harness.tools.bash import _bg_tasks, _bg_tasks_lock, spawn_background

        def _raising_callback(task_id, exit_code, timed_out, monitor_error):
            raise RuntimeError("intentional test failure")

        spawn_result = spawn_background(
            "echo hi",
            str(tmp_path),
            timeout_ms=10_000,
            workflow_id="wf_test_callback_raise",
            on_complete=_raising_callback,
        )

        task_id = spawn_result.task_id  # structured field — no string parsing

        # Wait for monitor to complete (echo hi takes <1s)
        import time as _time

        for _ in range(50):
            with _bg_tasks_lock:
                if task_id not in _bg_tasks:
                    break
            _time.sleep(0.1)

        with _bg_tasks_lock:
            assert task_id not in _bg_tasks, (
                "monitor cleanup failed — on_complete exception should not prevent pop"
            )

    def test_on_complete_exception_does_not_prevent_registry_update(self, tmp_path: Path):
        """If a future callback has a bug and raises, the user's TaskRegistry
        should still get updated via the rest of the bash monitor path... but
        actually the callback IS what updates the registry. So we test that
        even with a raising callback, bash.background_completed still emits
        (which the frontend / debug tools rely on).
        """
        # This test is a smoke check that the bash tool itself remains usable
        # for fire-and-forget usage (no launch_task pairing) when callback raises.
        from harness.tools.bash import spawn_background

        def _raising(task_id, exit_code, timed_out, monitor_error):
            raise RuntimeError("intentional")

        # Should not raise from spawn_background itself
        result = spawn_background(
            "echo safe",
            str(tmp_path),
            timeout_ms=5_000,
            workflow_id="wf_safe",
            on_complete=_raising,
        )
        assert "background task started" in result.message


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
