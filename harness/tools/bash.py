"""bash 工具 — 完全对照 Claude Code Bash 工具实现。

Schema 与行为对照（来自 Claude Code 系统提示）：
- 参数: command(str,必填) + description(str,必填) + timeout(int ms,默认 120000,最大 600000)
        + run_in_background(bool,默认 False)
- timeout 单位为毫秒，默认 120000ms (2 min)，最大 600000ms (10 min)
- 输出硬上限 30,000 字符；超出时把完整输出写到 .bash_outputs/{ts}_{hash}.log，
  返回前 ~2KB 预览 + 文件路径 + 提示 agent 用 read_text_file（filesystem MCP 已提供）
  按需读剩余内容
- run_in_background=True 时立即返回 task_id，命令在后台跑，完成时发
  bash.background_completed 事件

设计要点：
- 流式推送前端的行数有独立上限（MAX_STREAM_LINES），与 30K 字符上限解耦 ——
  防止 1500+ 行 stdout 全部推到 WS（即使最终返回被截断）
- foreground 进程和 background 任务都登记，stop 信号能同时 kill
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory

logger = logging.getLogger(__name__)

# Claude Code Bash 工具对照
DEFAULT_TIMEOUT_MS = 120_000      # 120s
MAX_TIMEOUT_MS = 600_000          # 600s
MAX_OUTPUT_CHARS = 30_000         # 返回值 / spill 文件的字符硬上限
PREVIEW_CHARS = 2_000             # 截断时内联预览大小
# 流式推送到前端的最多行数 — 与 MAX_OUTPUT_CHARS 解耦：
# 1500 行只是"WS 推送的软上限"，防止长输出风暴；最终返回给 LLM 的字符上限
# 始终是 MAX_OUTPUT_CHARS（即使 1500 行 × 短字符远低于 30K，超 30K 仍会被截断）。
MAX_STREAM_LINES = 1_500

# 后台任务注册表（task_id -> BackgroundTask）
_bg_tasks: dict[str, BackgroundTask] = {}
_bg_tasks_lock = threading.Lock()

# 前台进程按 workflow_id 索引（值是该 workflow 当前所有活跃 bash 进程的集合）。
# fan-out 场景下同一 workflow 可能并发跑多个 bash，所以用 set 而不是单个 Popen。
_running_procs: dict[str, set[subprocess.Popen]] = {}
_running_procs_lock = threading.Lock()


@dataclass
class BackgroundTask:
    task_id: str
    command: str
    workflow_id: str
    node_id: str
    agent_name: str
    output_path: str
    proc: subprocess.Popen
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    exit_code: int | None = None


def cancel_process(workflow_id: str) -> None:
    """Kill the running bash processes for a workflow (foreground + background)."""
    with _running_procs_lock:
        procs = list(_running_procs.get(workflow_id, set()))
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    with _bg_tasks_lock:
        tasks_to_kill = [t for t in _bg_tasks.values() if t.workflow_id == workflow_id]
    for t in tasks_to_kill:
        if t.proc.poll() is None:
            t.proc.terminate()


# ---------------------------------------------------------------------------
# EventBus helpers
# ---------------------------------------------------------------------------

def _emit_event(workflow_id: str, event_type: str, payload: dict) -> None:
    """Fire-and-forget event emission via the workflow's Bus."""
    if not workflow_id:
        return
    try:
        from server.repository import get_repository
        data = get_repository().get(workflow_id)
        bus = data.get("event_bus") if data else None
        if bus:
            bus.emit(event_type, payload)
    except Exception:
        logger.warning(
            "Failed to emit %s for workflow %s", event_type, workflow_id, exc_info=True,
        )


def _emit_line(workflow_id: str, node_id: str, agent_name: str, line: str, stream: str) -> None:
    _emit_event(workflow_id, "agent.tool_output_delta", {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "agent_name": agent_name,
        "tool_name": "bash",
        "line": line,
        "stream": stream,
    })


def _try_emit_chart(workflow_id: str, line: str) -> None:
    """Detect __HARNESS_CHART__: prefix in subprocess stdout and emit via EventBus."""
    prefix = "__HARNESS_CHART__:"
    if not line.startswith(prefix):
        return
    try:
        payload = json.loads(line[len(prefix):])
        _emit_event(workflow_id, "chart.render", payload)
    except Exception:
        logger.warning(
            "Failed to emit chart.render for workflow %s", workflow_id, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Output spill / truncation
# ---------------------------------------------------------------------------

def _output_dir(workdir: str) -> Path:
    """Get or create the bash output directory under workdir."""
    p = Path(workdir) / ".bash_outputs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_full_output(workdir: str, command: str, content: str, suffix: str = "") -> Path:
    """Write the full output to a deterministic file under .bash_outputs/.

    suffix is used to disambiguate background tasks (task_id) from foreground spills.
    """
    ts = int(time.time())
    cmd_hash = hashlib.md5(command.encode("utf-8", errors="replace")).hexdigest()[:8]
    name = f"{ts}_{cmd_hash}{suffix}.log" if suffix else f"{ts}_{cmd_hash}.log"
    path = _output_dir(workdir) / name
    path.write_text(content, encoding="utf-8", errors="replace")
    return path


def _build_truncated_result(full_text: str, output_path: Path) -> str:
    """Construct the value returned to the LLM when output exceeded MAX_OUTPUT_CHARS.

    对照 Claude Code: 内联 ~2KB 预览 + 总字符/行数 + 文件路径 + 用 read_text_file 读的提示。
    """
    preview = full_text[:PREVIEW_CHARS]
    total_chars = len(full_text)
    line_count = full_text.count("\n") + 1
    return (
        f"{preview}\n"
        f"\n[output truncated: {total_chars:,} chars / {line_count:,} lines total]\n"
        f"[full output saved to: {output_path}]\n"
        f"[use read_text_file to read on demand — e.g. read_text_file('{output_path}') "
        f"or use grep to find specific content]"
    )


# ---------------------------------------------------------------------------
# Process execution
# ---------------------------------------------------------------------------

def _reader(
    pipe,
    lines: list[str],
    stream_name: str,
    workflow_id: str,
    node_id: str,
    agent_name: str,
    emit: bool,
    line_counter: list[int],
) -> None:
    """Thread target: read pipe line-by-line, optionally stream to frontend."""
    for line in pipe:
        lines.append(line)
        stripped = line.rstrip("\n")
        if not stripped:
            continue
        # 流式推送有独立上限：超过 MAX_STREAM_LINES 后停止推 WS（避免风暴），
        # 但 lines 列表继续累积，最终参与 30K 截断判定
        if emit and line_counter[0] < MAX_STREAM_LINES:
            _emit_line(workflow_id, node_id, agent_name, stripped, stream_name)
            _try_emit_chart(workflow_id, stripped)
        line_counter[0] += 1


def _spawn_subprocess(command: str, workdir: str) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=workdir,
    )


def _assemble_full_text(
    stdout: str,
    stderr: str,
    returncode: int | None,
    *,
    timed_out: bool = False,
    timeout_ms: int | None = None,
) -> str:
    """Merge captured streams + returncode into the final text handed back / spilled.

    The "timed out" notice is a first-class prefix here (not jammed into stdout),
    so foreground (returned to LLM) and background (written to .bash_outputs/) get
    a consistent representation.
    """
    parts: list[str] = []
    if timed_out:
        parts.append(f"[command timed out after {timeout_ms}ms]" if timeout_ms else "[command timed out]")
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    if returncode == -15 or returncode == -9:
        parts.append("[killed by stop signal]")
    elif returncode is not None and returncode != 0:
        parts.append(f"[exit code: {returncode}]")
    return "\n".join(parts) if parts else "(no output)"


def _drain_pipes_and_wait(
    proc: subprocess.Popen,
    timeout_s: float,
    workflow_id: str,
    node_id: str,
    agent_name: str,
    emit: bool,
) -> tuple[str, str, bool]:
    """Start reader threads, wait (with timeout), return (stdout, stderr, timed_out).

    Note on ordering: stdout and stderr are drained by separate reader threads and
    concatenated as "stdout block, then stderr block". This loses the original
    interleaved time-order between streams (a trade-off for simpler truncation logic
    and the [stderr] label that helps debugging). If a future workflow needs strict
    ordering, switch to ``stderr=subprocess.STDOUT`` in ``_spawn_subprocess`` and
    drop the [stderr] tag — that aligns with Claude Code's behaviour.
    """
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    line_counter = [0]

    t_out = threading.Thread(
        target=_reader,
        args=(proc.stdout, stdout_lines, "stdout", workflow_id, node_id, agent_name, emit, line_counter),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_reader,
        args=(proc.stderr, stderr_lines, "stderr", workflow_id, node_id, agent_name, emit, line_counter),
        daemon=True,
    )
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
    finally:
        t_out.join(timeout=2)
        t_err.join(timeout=2)

    return "".join(stdout_lines), "".join(stderr_lines), timed_out


def _register_proc(workflow_id: str, proc: subprocess.Popen) -> None:
    """Track a foreground process so cancel_process(workflow_id) can kill it later."""
    if not workflow_id:
        return
    with _running_procs_lock:
        procs = _running_procs.setdefault(workflow_id, set())
        procs.add(proc)


def _unregister_proc(workflow_id: str, proc: subprocess.Popen) -> None:
    if not workflow_id:
        return
    with _running_procs_lock:
        procs = _running_procs.get(workflow_id)
        if procs is None:
            return
        procs.discard(proc)
        if not procs:
            _running_procs.pop(workflow_id, None)


def run_foreground(
    command: str,
    workdir: str,
    *,
    timeout_ms: int,
    workflow_id: str = "",
    node_id: str = "",
    agent_name: str = "",
    emit_stream: bool = True,
) -> str:
    """Run command to completion, return value to hand back to the LLM.

    Output exceeding MAX_OUTPUT_CHARS is spilled to .bash_outputs/ and a preview is returned.
    Emits agent.tool_output_truncated when spill occurs.
    """
    proc = _spawn_subprocess(command, workdir)
    _register_proc(workflow_id, proc)

    try:
        stdout, stderr, timed_out = _drain_pipes_and_wait(
            proc, timeout_ms / 1000, workflow_id, node_id, agent_name, emit_stream,
        )
    finally:
        _unregister_proc(workflow_id, proc)

    full_text = _assemble_full_text(
        stdout, stderr, proc.returncode, timed_out=timed_out, timeout_ms=timeout_ms,
    )

    if len(full_text) > MAX_OUTPUT_CHARS:
        out_path = _write_full_output(workdir, command, full_text)
        _emit_event(workflow_id, "agent.tool_output_truncated", {
            "workflow_id": workflow_id,
            "node_id": node_id,
            "agent_name": agent_name,
            "tool_name": "bash",
            "command": command,
            "output_path": str(out_path),
            "total_chars": len(full_text),
            "max_chars": MAX_OUTPUT_CHARS,
            "timed_out": timed_out,
        })
        return _build_truncated_result(full_text, out_path)

    return full_text


def spawn_background(
    command: str,
    workdir: str,
    *,
    timeout_ms: int,
    workflow_id: str = "",
    node_id: str = "",
    agent_name: str = "",
    description: str = "",
) -> str:
    """Spawn command in background. Returns a task_id-acknowledging string immediately.

    The command runs detached; when it completes (or times out) a bash.background_completed
    event fires with the result metadata. The full output is written to .bash_outputs/.

    On monitor failure, the task is still cleaned up (popped from _bg_tasks) and the
    event is emitted with exit_code=-1 and monitor_error=True so the frontend can
    distinguish "real success" from "monitor crashed".
    """
    proc = _spawn_subprocess(command, workdir)

    ts = int(time.time())
    cmd_hash = hashlib.md5(command.encode("utf-8", errors="replace")).hexdigest()[:8]
    task_id = f"bg_{ts}_{cmd_hash}"
    output_path = _write_full_output(workdir, command, "", suffix=f"_{task_id}")
    # _write_full_output already created the file; we'll overwrite on completion.

    task = BackgroundTask(
        task_id=task_id,
        command=command,
        workflow_id=workflow_id,
        node_id=node_id,
        agent_name=agent_name,
        output_path=str(output_path),
        proc=proc,
    )
    with _bg_tasks_lock:
        _bg_tasks[task_id] = task

    def _bg_monitor() -> None:
        monitor_error: str | None = None
        stdout = stderr = ""
        timed_out = False
        try:
            stdout, stderr, timed_out = _drain_pipes_and_wait(
                proc, timeout_ms / 1000, workflow_id, node_id, agent_name, emit=True,
            )
        except Exception as exc:
            monitor_error = repr(exc)
            logger.exception("background bash monitor failed for task %s", task_id)

        # If the monitor crashed before proc.wait(), returncode may be None —
        # surface that as an explicit non-zero so the event isn't mistaken for success.
        exit_code = proc.returncode if proc.returncode is not None else -1

        full_text = _assemble_full_text(
            stdout, stderr, exit_code, timed_out=timed_out, timeout_ms=timeout_ms,
        )
        truncated = len(full_text) > MAX_OUTPUT_CHARS

        try:
            output_path.write_text(full_text, encoding="utf-8", errors="replace")
        except Exception:
            logger.exception("failed to write background output to %s", output_path)

        task.completed_at = time.time()
        task.exit_code = exit_code

        _emit_event(workflow_id, "bash.background_completed", {
            "task_id": task_id,
            "command": command,
            "description": description,
            "workflow_id": workflow_id,
            "node_id": node_id,
            "agent_name": agent_name,
            "exit_code": exit_code,
            "output_chars": len(full_text),
            "truncated": truncated,
            "output_path": str(output_path),
            "timed_out": timed_out,
            "monitor_error": monitor_error,
        })

        # Cleanup: completed tasks are no longer actionable. cancel_process only needs
        # to find running tasks; leaving finished ones here would leak memory in
        # long-running servers.
        with _bg_tasks_lock:
            _bg_tasks.pop(task_id, None)

    threading.Thread(target=_bg_monitor, daemon=True).start()

    return (
        f"[background task started]\n"
        f"task_id: {task_id}\n"
        f"command: {command}\n"
        f"\nOutput will be saved to: {output_path}\n"
        f"A bash.background_completed event will fire when it finishes (or times out). "
        f"To check on it later, read_text_file('{output_path}')."
    )


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

class BashToolFactory(ToolFactory):
    """bash 工具 — 完全对照 Claude Code Bash 工具实现。"""

    name = "bash"
    description = (
        "Execute a bash command and return its output. "
        "Commands execute in the agent's working directory.\n\n"
        "WHEN TO USE A DEDICATED TOOL INSTEAD: prefer the dedicated "
        "Read/Grep/Glob tools over bash cat/find/grep/ls — they return "
        "structured, token-efficient results and integrate with the "
        "framework's truncation. Use bash only when no dedicated tool fits "
        "(running scripts, piped commands, git, build steps).\n\n"
        "DESTRUCTIVE COMMANDS (rm, mv, chmod, git push, git reset --hard, "
        "drop): state your intent in the description field before calling — "
        "these are hard to reverse.\n\n"
        "OUTPUT HANDLING: output over 30,000 chars is saved to "
        ".bash_outputs/{ts}_{hash}.log with a ~2KB inline preview; use "
        "read_text_file to page through the full output rather than "
        "re-running with head/tail.\n\n"
        "ON TIMEOUT: do not blindly retry the identical command. Split it "
        "into smaller steps, narrow the input, or raise the timeout — then "
        "say which you chose."
    )

    def __init__(self, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self.timeout_ms = timeout_ms

    def create(self) -> PydanticAITool:
        default_timeout = self.timeout_ms

        def bash(
            ctx: RunContext,
            command: str,
            description: str,
            timeout: int | None = None,
            run_in_background: bool = False,
        ) -> str:
            """Execute a bash command.

            Args:
                command: The shell command to execute.
                description: A short, clear description of what this command does
                    (5-10 words, active voice). Used for audit — included in the
                    bash.background_completed event payload so the UI can show what
                    the agent intended.
                    Example: "List files in current directory".
                timeout: Timeout in **milliseconds**. Default 120000 (2 min),
                    max 600000 (10 min). Use longer timeouts for long-running
                    scripts. If exceeded, the command is killed.
                run_in_background: When True, the command runs detached and this
                    returns immediately with a task_id. A bash.background_completed
                    event fires when it finishes (or times out). Use this for
                    long-running commands (builds, training, servers) that you
                    don't need to block on.
            """
            workdir = ctx.deps.workdir if isinstance(ctx.deps, AgentDeps) else "."
            wid = ctx.deps.workflow_id if isinstance(ctx.deps, AgentDeps) else ""
            node_id = ctx.deps.node_id if isinstance(ctx.deps, AgentDeps) else ""
            agent_name = ctx.deps.agent_name if isinstance(ctx.deps, AgentDeps) else ""

            effective_timeout = min(
                timeout if timeout is not None else default_timeout,
                MAX_TIMEOUT_MS,
            )

            try:
                if run_in_background:
                    return spawn_background(
                        command, workdir,
                        timeout_ms=effective_timeout,
                        workflow_id=wid, node_id=node_id, agent_name=agent_name,
                        description=description,
                    )
                return run_foreground(
                    command, workdir,
                    timeout_ms=effective_timeout,
                    workflow_id=wid, node_id=node_id, agent_name=agent_name,
                )
            except Exception as e:
                logger.exception("bash tool failed")
                return f"Error: {e}"

        return PydanticAITool(self._wrap_fn(bash, self.name), takes_ctx=True)
