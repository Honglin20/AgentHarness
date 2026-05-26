from __future__ import annotations

import subprocess
import threading

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 600

# Track running processes per workflow so stop signal can kill them
_running_procs: dict[str, subprocess.Popen] = {}


def cancel_process(workflow_id: str) -> None:
    """Kill the running bash process for a workflow (best-effort)."""
    proc = _running_procs.get(workflow_id)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def _emit_line(workflow_id: str, node_id: str, agent_name: str, line: str, stream: str) -> None:
    """Fire-and-forget: push a tool output delta event via the workflow's Bus."""
    if not workflow_id:
        return
    try:
        from server.repository import get_repository
        data = get_repository().get(workflow_id)
        bus = data.get("event_bus") if data else None
        if bus:
            bus.emit("agent.tool_output_delta", {
                "workflow_id": workflow_id,
                "node_id": node_id,
                "agent_name": agent_name,
                "tool_name": "bash",
                "line": line,
                "stream": stream,
            })
    except Exception:
        pass


class BashToolFactory(ToolFactory):
    """bash 工具 — 执行 shell 命令"""

    name = "bash"
    description = (
        "Execute a bash command and return its output. "
        "Use for running shell commands, scripts, and system operations. "
        "Commands execute in the agent's working directory."
    )

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout

    def create(self) -> PydanticAITool:
        default_timeout = self.timeout

        def bash(
            ctx: RunContext,
            command: str,
            timeout: int | None = None,
        ) -> str:
            """Execute a bash command.

            Args:
                command: The shell command to execute.
                timeout: Timeout in seconds. Defaults to 30, max 600.
                    Use longer timeouts for long-running scripts.
            """
            workdir = ctx.deps.workdir if isinstance(ctx.deps, AgentDeps) else "."
            wid = ctx.deps.workflow_id if isinstance(ctx.deps, AgentDeps) else ""
            node_id = ctx.deps.node_id if isinstance(ctx.deps, AgentDeps) else ""
            agent_name = ctx.deps.agent_name if isinstance(ctx.deps, AgentDeps) else ""
            effective_timeout = min(
                timeout if timeout is not None else default_timeout,
                MAX_TIMEOUT,
            )
            try:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=workdir,
                )
                if wid:
                    _running_procs[wid] = proc

                # Collect output in thread-safe lists while streaming to frontend
                stdout_lines: list[str] = []
                stderr_lines: list[str] = []

                def _reader(pipe, lines, stream_name):
                    for line in pipe:
                        lines.append(line)
                        stripped = line.rstrip("\n")
                        if stripped:
                            _emit_line(wid, node_id, agent_name, stripped, stream_name)

                t_out = threading.Thread(
                    target=_reader, args=(proc.stdout, stdout_lines, "stdout"), daemon=True,
                )
                t_err = threading.Thread(
                    target=_reader, args=(proc.stderr, stderr_lines, "stderr"), daemon=True,
                )
                t_out.start()
                t_err.start()

                try:
                    proc.wait(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    t_out.join(timeout=2)
                    t_err.join(timeout=2)
                    stdout = "".join(stdout_lines)
                    return f"Error: command timed out after {effective_timeout}s\n{stdout}"
                finally:
                    t_out.join(timeout=2)
                    t_err.join(timeout=2)
                    _running_procs.pop(wid, None)

                stdout = "".join(stdout_lines)
                stderr = "".join(stderr_lines)

                parts = []
                if stdout:
                    parts.append(stdout)
                if stderr:
                    parts.append(f"[stderr]\n{stderr}")
                if proc.returncode == -15 or proc.returncode == -9:
                    parts.append("[killed by stop signal]")
                elif proc.returncode != 0:
                    parts.append(f"[exit code: {proc.returncode}]")
                return "\n".join(parts) if parts else "(no output)"

            except Exception as e:
                return f"Error: {e}"

        return PydanticAITool(bash, takes_ctx=True)
