"""launch_task tool — structured launcher for long-running background tasks.

Distinct from bash(run_in_background=True) because:
  - Different defaults: timeout_ms=0 (never kill) vs bash's 120s
  - Encourages the launch+wait pairing (bash is fire-and-forget)
  - Phase 2 will add backend/metrics_path/detach fields without churn

Internal flow:
  1. Call bash.spawn_background with on_complete callback
  2. Register TaskRecord in TaskRegistry
  3. on_complete updates status to completed/failed/timeout when monitor observes end

The on_complete callback is invoked from bash.py's monitor daemon thread.
TaskRegistry updates are thread-safe (lock-guarded).
"""
from __future__ import annotations

import logging
import time

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.bash import BackgroundSpawnResult, spawn_background
from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory
from harness.tools.task_registry import (
    TERMINAL_STATUSES,
    TaskRecord,
    emit_task_event,
    get_task_registry,
)

logger = logging.getLogger(__name__)


class LaunchTaskToolFactory(ToolFactory):
    """launch_task — for training/eval/large downloads that take >1 minute.

    Pair with wait_for_tasks to block until completion. Do NOT use this without
    a following wait_for_tasks call (the DAG will move on immediately otherwise).
    """

    name = "launch_task"
    description = (
        "Launch a long-running task (training, evaluation, large downloads) in the "
        "background. Returns task_id immediately. ALWAYS pair with wait_for_tasks to "
        "block until completion. "
        "Default timeout_ms=0 means NEVER kill the process — DL training duration is "
        "unpredictable. Only set timeout_ms>0 as an explicit safety net."
    )

    def create(self) -> PydanticAITool:
        def launch_task(
            ctx: RunContext,
            command: str,
            description: str,
            *,
            timeout_ms: int = 0,
            expected_duration_s: int | None = None,
            progress_file: str | None = None,
        ) -> str:
            """Launch a long-running task. Returns task_id immediately.

            Args:
                command: The shell command to execute.
                description: Short description (shown in UI heartbeat).
                timeout_ms: Max wall-clock for the task. **DEFAULT 0 = NEVER kill.**
                    DL training duration is unpredictable; hardcoding a timeout risks
                    killing a 95%-complete run. Only set >0 as an explicit safety net
                    (nighttime batch, shared resource, suspected infinite loop).
                expected_duration_s: Optional hint for UI heartbeat ETA. Does NOT
                    affect execution. Set when you have a rough estimate.
                progress_file: Optional path the script writes progress JSON to
                    (e.g. {"epoch": 5, "loss": 0.32}). UI heartbeat surfaces this.

            Returns:
                String with task_id. Pass to wait_for_tasks to block until done:

                    task_id: bg_xxx
                    ...
                    wait_for_tasks(task_ids=['bg_xxx'])
            """
            workdir = ctx.deps.workdir if isinstance(ctx.deps, AgentDeps) else "."
            wid = ctx.deps.workflow_id if isinstance(ctx.deps, AgentDeps) else ""
            node_id = ctx.deps.node_id if isinstance(ctx.deps, AgentDeps) else ""
            agent_name = ctx.deps.agent_name if isinstance(ctx.deps, AgentDeps) else ""

            registry = get_task_registry(wid)
            started_at = time.time()

            # on_complete is called by bash.py's monitor thread when the subprocess ends.
            # Updates TaskRecord status so wait_for_tasks can observe completion.
            def _on_complete(
                task_id: str,
                exit_code: int,
                timed_out: bool,
                monitor_error: "str | None",
            ) -> None:
                # Race guard: if cancel_task already finalized this task (status=cancelled),
                # don't overwrite with completed/failed. Without this check, cancelling a
                # running task could see its status flipped back to "failed" when the
                # monitor observes process death. See TestCancelRaceWithOnComplete.
                existing = registry.get(task_id)
                if existing is not None and existing.status in TERMINAL_STATUSES:
                    return

                now = time.time()
                if monitor_error is not None:
                    status = "failed"
                elif timed_out:
                    status = "timeout"
                elif exit_code == 0:
                    status = "completed"
                else:
                    status = "failed"
                registry.update(
                    task_id,
                    status=status,
                    exit_code=exit_code,
                    completed_at=now,
                )
                emit_task_event(wid, f"task.{status}", {
                    "task_id": task_id,
                    "workflow_id": wid,
                    "node_id": node_id,
                    "agent_name": agent_name,
                    "exit_code": exit_code,
                    "description": description,
                    "elapsed_sec": round(now - started_at, 1),
                    "monitor_error": monitor_error,
                })

            spawn_result = spawn_background(
                command,
                workdir,
                timeout_ms=timeout_ms,
                workflow_id=wid,
                node_id=node_id,
                agent_name=agent_name,
                description=description,
                on_complete=_on_complete,
            )

            # spawn_background returns a structured result now (no string parsing).
            # task_id and output_path are first-class fields — see H3 fix.
            task_id = spawn_result.task_id
            output_path = spawn_result.output_path

            # Emit task.submitted BEFORE registry.register (M2 fix). If the
            # monitor thread fires task.completed in the microsecond window
            # between spawn_background return and registry.register, emitting
            # submitted first preserves event ordering (submitted → completed).
            # If we registered first then emitted, a fast task could produce
            # completed → submitted, which confuses bus replay / UI timeline.
            emit_task_event(wid, "task.submitted", {
                "task_id": task_id,
                "workflow_id": wid,
                "node_id": node_id,
                "agent_name": agent_name,
                "command": command,
                "description": description,
                "timeout_ms": timeout_ms,
                "expected_duration_s": expected_duration_s,
                "progress_file": progress_file,
            })

            registry.register(
                TaskRecord(
                    task_id=task_id,
                    workflow_id=wid,
                    node_id=node_id,
                    agent_name=agent_name,
                    command=command,
                    description=description,
                    output_path=output_path,
                    pid=spawn_result.pid,
                    started_at=started_at,
                    status="running",
                    timeout_ms=timeout_ms,
                    backend="local",
                    expected_duration_s=expected_duration_s,
                    progress_file=progress_file,
                )
            )

            return (
                f"task_id: {task_id}\n"
                f"command: {command}\n"
                f"description: {description}\n"
                f"\nNext step: call wait_for_tasks(task_ids=['{task_id}']) to block "
                f"until this task completes."
            )

        return PydanticAITool(self._wrap_fn(launch_task, self.name), takes_ctx=True)
