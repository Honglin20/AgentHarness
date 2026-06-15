from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai import RunContext, Tool as PydanticAITool

from harness.tools.deps import AgentDeps
from harness.constants import DEFAULT_MODEL
from harness.engine.llm import LLMClient
from harness.tools.registry import ToolFactory

if TYPE_CHECKING:
    from harness.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_EXCLUDE_FROM_CHILD = {"sub_agent", "ask_user"}


def _create_worktree(source_dir: str, task_id: str) -> tuple[str, bool]:
    """Create an isolated git worktree for a sub-agent.

    Returns (workdir, created) where created is True if a new worktree was
    actually created, False if it fell back to the source directory.

    The worktree path is logged loudly to aid debugging worktree-isolation
    issues (sub_agent code mutations leaking into main project dir).
    """
    source = Path(source_dir).resolve()
    wt_path = source.parent / f".wt_{task_id}"
    try:
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), "HEAD"],
            capture_output=True, text=True, check=True,
            cwd=str(source),
        )
        logger.warning(
            "sub_agent worktree CREATED: wt_path=%s, source=%s, git_stdout=%s",
            wt_path, source, result.stdout[:200],
        )
        for data_dir in ("data", "checkpoints", "datasets"):
            target = source / data_dir
            if target.is_dir():
                link = wt_path / data_dir
                if not link.exists():
                    link.symlink_to(target)
        return str(wt_path), True
    except (subprocess.CalledProcessError, OSError) as e:
        logger.warning(
            "Worktree creation FAILED (%s) — falling back to shared dir. "
            "sub_agent mutations WILL pollute main project dir! stderr=%s",
            e, getattr(e, 'stderr', '')[:200] if hasattr(e, 'stderr') else '',
        )
        return source_dir, False


def _cleanup_worktree(wt_path: str) -> None:
    """Remove a git worktree created by _create_worktree."""
    try:
        subprocess.run(
            ["git", "worktree", "remove", wt_path, "--force"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        logger.warning("Worktree cleanup failed for %s: %s", wt_path, e)


class SubAgentToolFactory(ToolFactory):
    """sub_agent 工具 — 委托子任务给临时 agent，支持并行和 worktree 隔离。"""

    name = "sub_agent"
    description = (
        "Launch a sub-agent to handle a specific task. "
        "Provide the task description and any relevant context. "
        "The sub-agent executes independently and returns its result. "
        "Sub-agents cannot spawn further sub-agents. "
        "Use for focused work that benefits from dedicated attention. "
        "When running multiple sub-agents in parallel, issue all calls "
        "in a single response — they execute concurrently. "
        "Use isolation='worktree' when sub-agents modify code to prevent conflicts."
    )

    def __init__(
        self,
        registry: ToolRegistry,
        model: str | None = None,
        max_depth: int = 1,
    ):
        self.registry = registry
        self.model = model or DEFAULT_MODEL
        self.max_depth = max_depth

    def create(self, depth: int = 0) -> PydanticAITool:
        registry = self.registry
        model = self.model
        max_depth = self.max_depth

        async def sub_agent(
            ctx: RunContext,
            task: str,
            isolation: str = "none",
        ) -> str:
            if depth >= max_depth:
                return "Error: maximum sub-agent depth reached"

            exclude = list(_EXCLUDE_FROM_CHILD)
            resolved_tools = registry.resolve(None, exclude=exclude)

            workdir = getattr(ctx.deps, "workdir", None) or "."
            task_id = f"sa_{uuid.uuid4().hex[:8]}"
            wt_created = False

            if isolation == "worktree":
                workdir, wt_created = _create_worktree(workdir, task_id)

            child_deps = AgentDeps(
                workdir=workdir,
                agent_name="sub_agent",
                depth=depth + 1,
            )

            parent_agg = getattr(ctx.deps, "token_aggregator", None)
            parent_name = getattr(ctx.deps, "agent_name", "unknown")

            client = LLMClient(model=model) if model else LLMClient()
            try:
                child = client.agent(
                    system_prompt="You are a sub-agent. Complete the assigned task concisely.",
                    output_type=str,
                    tools=resolved_tools,
                    deps_type=AgentDeps,
                )

                result = await child.run(task, deps=child_deps)

                if parent_agg is not None:
                    usage_obj = getattr(result, "usage", None)
                    if usage_obj is not None:
                        sub_key = f"{parent_name}.sub_agent"
                        parent_agg.record(
                            sub_key,
                            input_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
                            output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
                            cache_hit_tokens=getattr(usage_obj, "prompt_cache_hit_tokens", 0) or 0,
                            reasoning_tokens=getattr(usage_obj, "reasoning_tokens", 0) or 0,
                        )

                return result.output
            except Exception as e:
                logger.warning("sub_agent failed: %s: %s", type(e).__name__, e)
                return f"Error: sub-agent failed — {type(e).__name__}: {e}"
            finally:
                await client.aclose()
                if wt_created:
                    _cleanup_worktree(workdir)

        return PydanticAITool(self._wrap_fn(sub_agent, self.name), takes_ctx=True)
