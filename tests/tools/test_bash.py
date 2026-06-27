from __future__ import annotations

import subprocess
import time
from unittest.mock import patch

import pytest
from pydantic_ai import RunContext

from harness.tools.bash import (
    BashToolFactory,
    BackgroundTask,
    DEFAULT_TIMEOUT_MS,
    MAX_TIMEOUT_MS,
    MAX_OUTPUT_CHARS,
    PREVIEW_CHARS,
    _bg_tasks,
    _bg_tasks_lock,
    run_foreground,
    spawn_background,
)
from harness.tools.deps import AgentDeps


def _make_ctx(workdir: str = ".", agent_name: str = "test") -> RunContext[AgentDeps]:
    deps = AgentDeps(workdir=workdir, agent_name=agent_name)
    return RunContext(
        deps=deps,
        model=None,
        usage=None,
        prompt=None,
    )


class TestBashToolFactory:
    def test_name(self):
        factory = BashToolFactory()
        assert factory.name == "bash"

    def test_description_keywords(self):
        factory = BashToolFactory()
        # Core identity + decision guidance must be present. "shell" was dropped
        # when the description moved to decision-language (WHEN TO USE...); we
        # assert the decision info that replaced it instead.
        for keyword in ("bash", "command", "dedicated", "timeout"):
            assert keyword in factory.description.lower()

    def test_create_returns_tool(self):
        factory = BashToolFactory()
        tool = factory.create()
        assert tool is not None

    async def test_echo_execution(self):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = await bash_fn(ctx, command="echo hello", description="print hello")
        assert "hello" in result

    async def test_nonzero_exit_code(self):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = await bash_fn(ctx, command="exit 1", description="exit nonzero")
        assert "[exit code: 1]" in result

    async def test_stderr_captured(self):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = await bash_fn(ctx, command="echo error_msg >&2", description="emit stderr")
        assert "error_msg" in result
        assert "[stderr]" in result

    async def test_timeout(self):
        # 1000ms timeout, sleep 10s → should time out
        factory = BashToolFactory(timeout_ms=1000)
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = await bash_fn(ctx, command="sleep 10", description="sleep ten seconds")
        assert "timed out" in result
        assert "1000ms" in result

    async def test_timeout_records_last_tool_failure(self):
        """TASK 2: a timeout writes a structured failure to deps (side-channel).

        The returned string is unchanged (model still sees the timed-out
        output); deps.last_tool_failure carries the structured failure +
        actionable hint for runtime_status to surface next turn.
        """
        factory = BashToolFactory(timeout_ms=1000)
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = await bash_fn(ctx, command="sleep 10", description="sleep ten seconds")
        # Return value unchanged.
        assert "timed out" in result
        # Side-channel failure recorded.
        f = ctx.deps.last_tool_failure
        assert f is not None
        assert f["tool"] == "bash"
        assert "timed out" in f["error"]
        assert f["hint"]  # actionable guidance present

    async def test_nonzero_exit_with_stderr_records_failure(self):
        """TASK 2: non-zero exit + visible stderr records a failure."""
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = await bash_fn(ctx, command="ls /nonexistent_dir_xyz", description="ls missing dir")
        assert "[exit code:" in result and "[stderr]" in result
        f = ctx.deps.last_tool_failure
        assert f is not None and f["tool"] == "bash" and "exit code" in f["error"]

    async def test_success_does_not_record_failure(self):
        """TASK 2: a clean exit (code 0) must NOT set last_tool_failure."""
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        await bash_fn(ctx, command="echo ok", description="echo ok")
        assert ctx.deps.last_tool_failure is None

    async def test_nonzero_exit_without_stderr_does_not_record_failure(self):
        """TASK 2: non-zero exit with NO stderr is not actionable → not recorded.

        Many tools exit non-zero on benign conditions (grep no-match). Without
        stderr the failure gives the model nothing to act on, so we stay quiet.
        """
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        # `true` exits 0; use a command that exits 1 with empty stderr.
        result = await bash_fn(ctx, command="exit 1", description="exit 1 no stderr")
        assert "[exit code: 1]" in result
        assert ctx.deps.last_tool_failure is None

    async def test_python_exception_records_last_tool_failure(self):
        """A Python-level exception (not a subprocess exit) must also record a
        failure, so runtime_status can surface it next turn.

        Regression for the half-finished write-end: only the marker-based path
        (timeout / non-zero-exit) recorded failures; a bare ``except Exception``
        returned "Error: {e}" but left last_tool_failure null, so the dynamic
        status layer stayed mute when the command couldn't run at all (bad
        workdir, missing binary, etc.). Now both paths write the same shape.
        """
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        # Force run_foreground to raise — simulates a pre-subprocess failure.
        with patch(
            "harness.tools.bash.run_foreground",
            side_effect=FileNotFoundError("workdir does not exist"),
        ):
            result = await bash_fn(ctx, command="echo ok", description="echo ok")
        # The model still sees the error string.
        assert "Error: workdir does not exist" in result
        # And the side-channel failure is recorded (same {tool,error,hint} shape).
        f = ctx.deps.last_tool_failure
        assert f is not None
        assert f["tool"] == "bash"
        assert "workdir does not exist" in f["error"]
        assert f["hint"]  # actionable guidance present

    def test_default_timeout(self):
        assert DEFAULT_TIMEOUT_MS == 120_000
        factory = BashToolFactory()
        assert factory.timeout_ms == DEFAULT_TIMEOUT_MS

    def test_custom_timeout_ms(self):
        factory = BashToolFactory(timeout_ms=60_000)
        assert factory.timeout_ms == 60_000

    async def test_max_timeout_enforced(self):
        # Caller passes > MAX_TIMEOUT_MS via run-time arg; factory should clamp it.
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        # Patch run_foreground to capture the effective timeout_ms without running
        with patch("harness.tools.bash.run_foreground") as mock_run:
            mock_run.return_value = "(mocked)"
            await bash_fn(
                ctx,
                command="echo hi",
                description="test",
                timeout=999_999_999,  # way over the cap
            )
            args, kwargs = mock_run.call_args
            assert kwargs["timeout_ms"] == MAX_TIMEOUT_MS

    async def test_workdir_respected(self, tmp_path):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx(workdir=str(tmp_path))
        result = await bash_fn(ctx, command="pwd", description="print working dir")
        assert str(tmp_path) in result

    async def test_no_output(self):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = await bash_fn(ctx, command="true", description="no-op true")
        assert result == "(no output)"

    async def test_description_is_required(self):
        # Schema requires description; calling without it should TypeError
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        with pytest.raises(TypeError):
            await bash_fn(ctx, command="echo hi")  # missing description


class TestOutputTruncation:
    """对照 Claude Code: >30K chars spilled to disk + ~2KB preview returned."""

    def test_short_output_not_truncated(self, tmp_path):
        result = run_foreground(
            "echo short output",
            str(tmp_path),
            timeout_ms=10_000,
        )
        assert "short output" in result
        assert "truncated" not in result

    def test_long_output_truncated_and_spilled(self, tmp_path):
        # Generate ~50K chars of output (well over the 30K cap)
        result = run_foreground(
            "yes 'x' | head -c 50000",
            str(tmp_path),
            timeout_ms=10_000,
        )
        # Preview present (first chars)
        assert "x" in result
        # Truncation notice present
        assert "output truncated" in result
        # File path mentioned
        assert ".bash_outputs" in result
        # Full output saved to disk
        log_files = list((tmp_path / ".bash_outputs").glob("*.log"))
        assert len(log_files) == 1
        spilled_content = log_files[0].read_text()
        assert len(spilled_content) > MAX_OUTPUT_CHARS
        # Inline result is bounded by preview + notice (well under the cap)
        assert len(result) < PREVIEW_CHARS + 1000  # preview + notice overhead

    def test_truncated_result_includes_read_hint(self, tmp_path):
        result = run_foreground(
            "yes 'x' | head -c 50000",
            str(tmp_path),
            timeout_ms=10_000,
        )
        # Agent should be told to use read_text_file
        assert "read_text_file" in result


class TestRunInBackground:
    """对照 Claude Code: run_in_background=True returns task_id immediately."""

    def test_background_returns_immediately(self, tmp_path):
        start = time.monotonic()
        result = spawn_background(
            "sleep 2",
            str(tmp_path),
            timeout_ms=10_000,
            workflow_id="wf_test_bg",
            node_id="test_node",
            agent_name="test_agent",
        )
        elapsed = time.monotonic() - start
        # Should return within 1 second (sleep 2 hasn't finished)
        assert elapsed < 1.0
        assert "[background task started]" in result
        assert "task_id: bg_" in result

        # Wait for background task to finish so it doesn't pollute the next test.
        # The monitor thread fires bash.background_completed asynchronously.
        time.sleep(2.5)

    def test_background_registers_task(self, tmp_path):
        # Capture emitted events via a fake bus. patcher must outlive the
        # with-block because the monitor thread runs asynchronously.
        emitted_events: list[tuple[str, dict]] = []

        def fake_emit(workflow_id, event_type, payload):
            emitted_events.append((event_type, payload))

        patcher = patch("harness.tools.bash._emit_event", side_effect=fake_emit)
        patcher.start()
        try:
            result = spawn_background(
                "echo hi && sleep 1",
                str(tmp_path),
                timeout_ms=10_000,
                workflow_id="wf_test_bg2",
                node_id="n",
                agent_name="a",
                description="test background echo",
            )
            # Extract task_id from result string
            task_id_line = [line for line in result.split("\n") if line.startswith("task_id:")][0]
            task_id = task_id_line.split(":", 1)[1].strip()

            # Right after spawn: task is registered
            with _bg_tasks_lock:
                assert task_id in _bg_tasks
                task = _bg_tasks[task_id]
                assert task.workflow_id == "wf_test_bg2"
                assert task.command == "echo hi && sleep 1"

            # Wait for background completion + cleanup
            time.sleep(2.0)
        finally:
            patcher.stop()

        # After completion: task is popped from registry (review #4 cleanup)
        with _bg_tasks_lock:
            assert task_id not in _bg_tasks

        # But the task object itself was completed with the right state
        assert task.completed_at is not None
        assert task.exit_code == 0

        # Output file was written
        from pathlib import Path
        assert Path(task.output_path).exists()
        content = Path(task.output_path).read_text()
        assert "hi" in content

        # Completion event was emitted with all expected fields
        completed = [e for e in emitted_events if e[0] == "bash.background_completed"]
        assert len(completed) == 1
        payload = completed[0][1]
        assert payload["task_id"] == task_id
        assert payload["exit_code"] == 0
        assert payload["description"] == "test background echo"
        assert payload["monitor_error"] is None
        assert "output_path" in payload

    async def test_background_via_tool_function(self, tmp_path):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx(workdir=str(tmp_path))
        start = time.monotonic()
        result = await bash_fn(
            ctx,
            command="sleep 3",
            description="long sleep in background",
            run_in_background=True,
        )
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        assert "[background task started]" in result


class TestStreamLineLimit:
    """流式推送前端有独立上限（防 WS 风暴），不影响最终返回的截断判定。"""

    def test_many_lines_dont_break_tool(self, tmp_path):
        # 1800 lines of small output — over MAX_STREAM_LINES (1500) but
        # under MAX_OUTPUT_CHARS (30K). Tool should return all lines, not truncate.
        result = run_foreground(
            "seq 1800",
            str(tmp_path),
            timeout_ms=15_000,
        )
        assert "1\n" in result
        assert "1800" in result
        assert "truncated" not in result
