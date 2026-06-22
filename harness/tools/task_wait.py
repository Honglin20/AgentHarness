"""wait_for_tasks / list_tasks / cancel_task tools.

wait_for_tasks is the key primitive that was missing from the harness:
it lets an agent block until a previously-launched background task reaches
a terminal state. Uses asyncio.sleep for polling (yields control to the
event loop — other workflows/agents keep running).

Emits task.heartbeat every 30s (normal priority) so UI can distinguish
"still waiting" from "stuck" for multi-hour training.
"""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.bash import cancel_process
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory
from harness.tools.task_registry import (
    COMMAND_PREVIEW_CHARS,
    TERMINAL_STATUSES,
    emit_task_event,
    get_task_registry,
    read_output_tail,
    read_progress,
)

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0
DEFAULT_POLL_INTERVAL_MS = 2_000


def _emit_heartbeat(task_ids: list[str], workflow_id: str) -> None:
    """Emit task.heartbeat for each still-running task in the list.

    Payload includes elapsed_sec, optional ETA (if expected_duration_s was set),
    optional progress (if progress_file is being written), and output_tail
    (last 500 chars of stdout/stderr).
    """
    registry = get_task_registry(workflow_id)
    now = time.time()
    for tid in task_ids:
        task = registry.get(tid)
        if task is None or task.status in TERMINAL_STATUSES:
            continue
        elapsed = now - task.started_at
        expected_remaining = None
        if task.expected_duration_s:
            expected_remaining = max(0.0, task.expected_duration_s - elapsed)
        progress = read_progress(task.progress_file)
        emit_task_event(workflow_id, "task.heartbeat", {
            "task_id": tid,
            "workflow_id": workflow_id,
            "elapsed_sec": round(elapsed, 1),
            "expected_remaining_sec": (
                round(expected_remaining, 1) if expected_remaining is not None else None
            ),
            "progress": progress,
            "output_tail": read_output_tail(task.output_path),
        })


def _format_summary(
    task_ids: list[str],
    workflow_id: str,
    *,
    elapsed: float,
    client_timeout: bool,
    unknown: list[str],
) -> str:
    """Build the structured summary string returned by wait_for_tasks."""
    registry = get_task_registry(workflow_id)
    lines: list[str] = []
    terminal_count = 0
    for tid in task_ids:
        task = registry.get(tid)
        if task is None:
            lines.append(f"task_id={tid}  status=unknown")
            continue
        if task.status in TERMINAL_STATUSES:
            terminal_count += 1
        exit_str = str(task.exit_code) if task.exit_code is not None else "n/a"
        out_str = task.output_path or "(no output path)"
        lines.append(
            f"task_id={tid}  status={task.status}  exit={exit_str}  output={out_str}"
        )
    header = f"[{terminal_count}/{len(task_ids)} tasks terminal in {elapsed:.1f}s"
    if client_timeout:
        header += "  client_timeout=true"
    header += "]"
    body = "\n".join(lines) if lines else "(no tasks)"
    extra = f"\nunknown task_ids: {unknown}" if unknown else ""
    hint = (
        "\n\nUse read_text_file to inspect any output. "
        "If status=failed, read the output log to diagnose."
    )
    return f"{header}\n{body}{extra}{hint}"


async def _wait_for_tasks_impl(
    task_ids: list[str],
    workflow_id: str,
    *,
    timeout_ms: int = 0,
    poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS,
) -> str:
    """Block until all known task_ids reach terminal state, or client timeout.

    Unknown task_ids at entry are reported in the summary but don't block.
    Re-checked each poll iteration: if a task that was unknown at entry gets
    registered later (e.g. concurrent launch_task in a sub_agent fan-out), it
    is promoted to known and waited on. This prevents the race where a
    parallel launcher registers the task after wait_for_tasks was called.
    """
    registry = get_task_registry(workflow_id)

    # Initial partition — but we re-check inside the loop because the registry
    # can gain entries from concurrent launch_task calls.
    known = [tid for tid in task_ids if registry.get(tid) is not None]
    unknown = [tid for tid in task_ids if registry.get(tid) is None]

    if not known and not unknown:
        return "[no tasks to wait for]"

    if not known:
        # All unknown at entry — still enter the loop briefly, in case a
        # concurrent launch_task registers one. Short grace period (1 poll
        # interval) before giving up.
        pass

    # If everything is already terminal, return immediately.
    if known and all(registry.get(tid).status in TERMINAL_STATUSES for tid in known):
        return _format_summary(
            known, workflow_id,
            elapsed=0.0, client_timeout=False, unknown=unknown,
        )

    deadline = (time.monotonic() + timeout_ms / 1000) if timeout_ms > 0 else None
    last_heartbeat = 0.0
    start = time.monotonic()
    # Give "all unknown at entry" a short grace period for concurrent registration.
    unknown_grace_deadline = time.monotonic() + poll_interval_ms / 1000.0

    while True:
        # Re-partition: tasks that were unknown may have been registered by a
        # concurrent launch_task (H1 fix — fan-out race).
        still_unknown: list[str] = []
        for tid in unknown:
            if registry.get(tid) is not None:
                known.append(tid)
            else:
                still_unknown.append(tid)
        unknown = still_unknown

        if not known:
            # Nothing to wait on. Exit after the grace period to avoid busy-loop.
            if time.monotonic() > unknown_grace_deadline:
                return (
                    f"[no known tasks to wait for]\n"
                    f"unknown task_ids: {unknown}\n"
                    f"\nCheck task_ids returned by launch_task, or call list_tasks()."
                )
        else:
            tasks = [registry.get(tid) for tid in known]
            statuses = [t.status if t else "unknown" for t in tasks]
            if all(s in TERMINAL_STATUSES for s in statuses):
                return _format_summary(
                    known, workflow_id,
                    elapsed=time.monotonic() - start,
                    client_timeout=False, unknown=unknown,
                )

        now = time.monotonic()
        if deadline is not None and now > deadline:
            return _format_summary(
                known, workflow_id,
                elapsed=time.monotonic() - start,
                client_timeout=True, unknown=unknown,
            )

        # Heartbeat every HEARTBEAT_INTERVAL_S while still waiting
        if known and now - last_heartbeat > HEARTBEAT_INTERVAL_S:
            _emit_heartbeat(known, workflow_id)
            last_heartbeat = now

        await asyncio.sleep(poll_interval_ms / 1000)


# ──────────────────────────────────────────────────────────────────────
# Tool factories
# ──────────────────────────────────────────────────────────────────────


class WaitForTasksToolFactory(ToolFactory):
    """wait_for_tasks — block until task_ids reach terminal state."""

    name = "wait_for_tasks"
    description = (
        "Block until all specified tasks reach a terminal state "
        "(completed/failed/timeout/cancelled). Returns a summary with status, "
        "exit_code, and output_path per task. Default timeout_ms=0 means wait "
        "indefinitely (recommended — task duration is unpredictable). "
        "Emits task.heartbeat every 30s while waiting so UI shows progress."
    )

    def create(self) -> PydanticAITool:
        async def wait_for_tasks(
            ctx: RunContext,
            task_ids: list[str],
            *,
            timeout_ms: int = 0,
            poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS,
        ) -> str:
            """Wait for long-running tasks to finish.

            Args:
                task_ids: List of task_ids returned by launch_task.
                timeout_ms: Max time YOU (the agent) will wait. 0 = wait forever.
                    If expired, returns with client_timeout=true in the summary;
                    tasks keep running in the background.
                poll_interval_ms: Polling interval (default 2s). Lower = faster
                    detection but more CPU. For multi-hour tasks, consider raising
                    to 10s+ to reduce wakeups.

            Returns:
                Structured summary:

                    [2/2 tasks terminal in 58.3s]
                    task_id=bg_a  status=completed  exit=0  output=runs/.../a.log
                    task_id=bg_b  status=failed     exit=1  output=runs/.../b.log

                    Use read_text_file to inspect any output.
            """
            wid = ctx.deps.workflow_id if isinstance(ctx.deps, AgentDeps) else ""
            return await _wait_for_tasks_impl(
                task_ids,
                wid,
                timeout_ms=timeout_ms,
                poll_interval_ms=poll_interval_ms,
            )

        return PydanticAITool(self._wrap_fn(wait_for_tasks, self.name), takes_ctx=True)


class ListTasksToolFactory(ToolFactory):
    """list_tasks — debugging affordance for inspecting task state."""

    name = "list_tasks"
    description = (
        "List tasks visible to this workflow, optionally filtered by status. "
        "Use for debugging or when you've lost track of task_ids."
    )

    def create(self) -> PydanticAITool:
        def list_tasks(
            ctx: RunContext,
            *,
            status: str | None = None,
        ) -> str:
            """List tasks for this workflow.

            Args:
                status: Optional filter — one of submitted/running/completed/
                    failed/timeout/cancelled. None = list all.
            """
            wid = ctx.deps.workflow_id if isinstance(ctx.deps, AgentDeps) else ""
            registry = get_task_registry(wid)
            tasks = registry.list_all()
            if status:
                tasks = [t for t in tasks if t.status == status]
            if not tasks:
                return f"[no tasks{' with status='+status if status else ''}]"
            lines = []
            for t in tasks:
                exit_str = str(t.exit_code) if t.exit_code is not None else "n/a"
                cmd_preview = (
                    t.command[:COMMAND_PREVIEW_CHARS]
                    + ("..." if len(t.command) > COMMAND_PREVIEW_CHARS else "")
                )
                lines.append(
                    f"task_id={t.task_id}  status={t.status}  exit={exit_str}  "
                    f"cmd={cmd_preview}"
                )
            return "\n".join(lines)

        return PydanticAITool(self._wrap_fn(list_tasks, self.name), takes_ctx=True)


class CancelTaskToolFactory(ToolFactory):
    """cancel_task — kill a running task by task_id.

    MVP: workflow-wide cancel (kills all procs for this workflow via the existing
    cancel_process helper). Finer-grained single-task cancel in Phase 2 once
    Popen objects are exposed via TaskRecord.pid.
    """

    name = "cancel_task"
    description = (
        "Cancel ALL running tasks for this workflow (MVP behavior — single-task "
        "cancel is Phase 2). Useful for aborting a failed experiment batch. "
        "Kills the underlying processes, marks the specified task_id as cancelled, "
        "and emits task.cancelled event. WARNING: any sibling tasks launched by "
        "parallel sub_agents will also be killed."
    )

    def create(self) -> PydanticAITool:
        def cancel_task(ctx: RunContext, task_id: str) -> str:
            """Cancel a task. Marks status=cancelled and kills its process.

            Args:
                task_id: The task to cancel.
            """
            wid = ctx.deps.workflow_id if isinstance(ctx.deps, AgentDeps) else ""
            registry = get_task_registry(wid)
            task = registry.get(task_id)
            if task is None:
                return f"Error: unknown task_id {task_id}"
            if task.status in TERMINAL_STATUSES:
                return (
                    f"task_id={task_id} already in terminal state "
                    f"({task.status}); nothing to cancel."
                )
            # MVP: workflow-wide cancel. cancel_process kills all procs for this
            # workflow_id (both foreground bash + background tasks). Finer-grained
            # single-task cancel needs TaskRecord.pid to be plumbed through, which
            # is Phase 2.
            cancel_process(wid)
            now = time.time()
            registry.update(task_id, status="cancelled", completed_at=now, exit_code=-15)
            emit_task_event(wid, "task.cancelled", {
                "task_id": task_id,
                "workflow_id": wid,
                "node_id": task.node_id,
                "agent_name": task.agent_name,
            })
            return (
                f"cancelled task_id={task_id}\n"
                f"Note: workflow-wide cancel was used (kills all running tasks for "
                f"workflow {wid}). Finer-grained cancel is Phase 2."
            )

        return PydanticAITool(self._wrap_fn(cancel_task, self.name), takes_ctx=True)
