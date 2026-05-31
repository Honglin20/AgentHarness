from __future__ import annotations

import os
import shutil
import subprocess

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.tools.registry import ToolFactory

MAX_COLUMNS = 500
DEFAULT_HEAD_LIMIT = 250
MAX_OUTPUT_CHARS = 50_000


def _find_rg() -> str | None:
    """Find ripgrep binary. Search $PATH, then common locations."""
    # shutil.which doesn't always find it (conda path issue)
    path = shutil.which("rg")
    if path:
        return path
    try:
        r = subprocess.run(
            ["bash", "-lc", "command -v rg"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _resolve_path(path: str | None, workdir: str) -> str:
    """Resolve a potentially relative path against the working directory."""
    if not path:
        return workdir
    if os.path.isabs(path):
        return path
    return os.path.join(workdir, path)


class GrepToolFactory(ToolFactory):
    """grep 工具 — 基于 ripgrep 的内容搜索"""

    name = "grep"
    description = (
        "A powerful search tool built on ripgrep. "
        "Searches file contents for regex patterns. Supports file type filtering, "
        "context lines, case-insensitive mode, and multiple output formats. "
        "Use this tool instead of bash grep for structured, token-efficient results."
    )

    def create(self) -> PydanticAITool:
        def grep(
            ctx: RunContext,
            pattern: str,
            path: str | None = None,
            output_mode: str = "files_with_matches",
            glob: str | None = None,
            type: str | None = None,
            case_insensitive: bool = False,
            context: int | None = None,
            before_context: int | None = None,
            after_context: int | None = None,
            multiline: bool = False,
            head_limit: int = DEFAULT_HEAD_LIMIT,
        ) -> str:
            """Search file contents for a regex pattern.

            Args:
                pattern: The regular expression pattern to search for.
                path: File or directory to search in. Defaults to working directory.
                output_mode: "files_with_matches" (default), "content", or "count".
                glob: Glob pattern to filter files (e.g. "*.py", "*.{ts,tsx}").
                type: File type to search (py, js, rust, go, java, etc.).
                case_insensitive: Case-insensitive search.
                context: Number of lines to show before and after each match.
                before_context: Number of lines before each match.
                after_context: Number of lines after each match.
                multiline: Enable multiline mode where . matches newlines.
                head_limit: Max number of result lines/entries (default 250).
            """
            workdir = ctx.deps.workdir if isinstance(ctx.deps, AgentDeps) else "."
            rg = _find_rg()
            if rg is None:
                return (
                    "Error: ripgrep (rg) not found. "
                    "Install it with: brew install ripgrep / apt install ripgrep / conda install ripgrep"
                )

            target = _resolve_path(path, workdir)

            args = [rg, "--no-heading", "--with-filename"]
            args += ["--max-columns", str(MAX_COLUMNS)]

            # Exclude common non-source directories
            for d in [".git", ".svn", ".hg", "node_modules", "__pycache__", ".codegraph"]:
                args += ["--glob", f"!{d}"]

            if output_mode == "count":
                args.append("--count")
            elif output_mode == "content":
                args.append("--line-number")
            # files_with_matches is rg's default with no extra flag

            if case_insensitive:
                args.append("-i")
            if multiline:
                args += ["-U", "--multiline-dotall"]
            if glob:
                args += ["--glob", glob]
            if type:
                args += ["--type", type]
            if context:
                args += ["-C", str(context)]
            if before_context:
                args += ["-B", str(before_context)]
            if after_context:
                args += ["-A", str(after_context)]

            args.append("--")
            args.append(pattern)
            args.append(target)

            try:
                r = subprocess.run(
                    args, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                return "Error: grep timed out after 30s"

            # rg exit code 1 = no matches, 2+ = error
            if r.returncode == 1:
                return "No matches found"
            if r.returncode >= 2:
                return f"Error: {r.stderr.strip()}" if r.stderr else f"Error: rg exited with code {r.returncode}"

            output = r.stdout
            if not output:
                return "No matches found"

            # Apply head_limit
            lines = output.splitlines()
            truncated = len(lines) > head_limit
            if truncated:
                lines = lines[:head_limit]

            result = "\n".join(lines)

            # Truncate if too long
            if len(result) > MAX_OUTPUT_CHARS:
                result = result[:MAX_OUTPUT_CHARS] + "\n... (truncated)"

            if truncated:
                result += f"\n... ({len(lines)}/{len(output.splitlines())} results shown, use head_limit to see more)"

            return result

        return PydanticAITool(grep, takes_ctx=True)


class GlobToolFactory(ToolFactory):
    """glob 工具 — 基于 ripgrep 的文件模式匹配"""

    name = "glob"
    description = (
        "Fast file pattern matching tool. "
        "Supports glob patterns like '**/*.js' or 'src/**/*.ts'. "
        "Returns matching file paths sorted by modification time. "
        "Use this tool instead of bash find/ls for structured, token-efficient results."
    )

    def create(self) -> PydanticAITool:
        def glob(
            ctx: RunContext,
            pattern: str,
            path: str | None = None,
        ) -> str:
            """Find files matching a glob pattern.

            Args:
                pattern: The glob pattern to match files against (e.g. "**/*.py", "src/**/*.ts").
                path: The directory to search in. Defaults to working directory.
            """
            workdir = ctx.deps.workdir if isinstance(ctx.deps, AgentDeps) else "."
            rg = _find_rg()
            if rg is None:
                return (
                    "Error: ripgrep (rg) not found. "
                    "Install it with: brew install ripgrep / apt install ripgrep / conda install ripgrep"
                )

            target = _resolve_path(path, workdir)

            args = [
                rg, "--files",
                "--glob", pattern,
                "--sort=modified",
                "--hidden",
            ]

            # Exclude common non-source directories
            for d in [".git", ".svn", ".hg", "node_modules", "__pycache__", ".codegraph"]:
                args += ["--glob", f"!{d}"]

            args.append(target)

            try:
                r = subprocess.run(
                    args, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                return "Error: glob timed out after 30s"

            if r.returncode != 0 and r.stderr:
                return f"Error: {r.stderr.strip()}"

            lines = [l for l in r.stdout.splitlines() if l.strip()]
            if not lines:
                return "No files found"

            # Convert absolute paths to relative (against workdir) to save tokens
            rel_lines = []
            for line in lines:
                try:
                    rel = os.path.relpath(line, workdir)
                    # Only use relative if it's shorter
                    rel_lines.append(rel if len(rel) < len(line) else line)
                except ValueError:
                    rel_lines.append(line)

            # Cap at 100 results
            truncated = len(rel_lines) > 100
            if truncated:
                rel_lines = rel_lines[:100]

            result = "\n".join(rel_lines)
            if truncated:
                result += f"\n... (showing 100/{len(lines)} files)"

            return result

        return PydanticAITool(glob, takes_ctx=True)
