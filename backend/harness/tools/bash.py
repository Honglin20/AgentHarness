from __future__ import annotations

import subprocess

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory

DEFAULT_TIMEOUT = 30


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
        timeout = self.timeout

        def bash(ctx: RunContext, command: str) -> str:
            workdir = ctx.deps.workdir if ctx.deps and hasattr(ctx.deps, "workdir") else "."
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=workdir,
                )
                output = result.stdout
                if result.stderr:
                    output += f"\n[stderr]\n{result.stderr}"
                if result.returncode != 0:
                    output += f"\n[exit code: {result.returncode}]"
                return output or "(no output)"
            except subprocess.TimeoutExpired:
                return f"Error: command timed out after {timeout}s"

        return PydanticAITool(bash, takes_ctx=True)
