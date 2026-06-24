from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import iscoroutinefunction
from enum import Enum
from fnmatch import fnmatchcase
from functools import wraps
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Tool as PydanticAITool


class ToolCatalogEntry(BaseModel):
    """A single tool's metadata for the catalog API."""
    name: str
    description: str
    source: str  # "built-in" | "mcp_filesystem" | "mcp_codegraph" | "mcp_custom"
    parameters: dict[str, Any] = {}


class ToolNotFoundError(Exception):
    pass


class ToolTier(Enum):
    """Three-tier tool loading model.

    FORCED   — always injected into every agent's tool list, even when the
               agent has an explicit `tools` whitelist. Excluded only by an
               explicit `exclude=[...]` entry. Use for framework-mandated
               tools (currently: `todo`).

    DEFAULT  — loaded when `tools=None` (the common case). Replaced by the
               whitelist when the agent specifies one. Use for general-
               purpose infrastructure every agent is likely to need (bash,
               filesystem, etc.).

    EXPLICIT — never auto-loaded. The agent must list the tool by name
               (or via glob like `codegraph_*`) to receive it. Use for
               heavyweight or scenario-specific tools (codegraph,
               render_chart).
    """
    FORCED = "forced"
    DEFAULT = "default"
    EXPLICIT = "explicit"


class ToolFactory(ABC):
    """Abstract tool factory — subclasses must implement create()."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def create(self) -> PydanticAITool: ...

    def _wrap_fn(self, fn, tool_name: str):
        """Wrap a tool function with the full tool lifecycle.

        Pipeline (every tool, every call):
          0. dedup guard          — skip duplicate calls within the window
          1. PreToolUse dispatch  — before_tool middleware (block / rewrite)
          2. execute              — the raw tool fn
          3. truncate             — bound message_history growth (existing)
          4. PostToolUse dispatch — after_tool middleware (substitute / flag)
          5. measure              — emit agent.tool_output_measured (TASK 0)

        ONE async wrapper serves both sync and async tool fns: sync fns are
        run via ``anyio.to_thread.run_sync`` so Pre/PostToolUse dispatch
        (which is async) works uniformly. This matters because the heaviest
        output producers (bash/grep/glob) are sync — they most need
        PostToolUse compaction, so they must not be excluded from dispatch.

        Robustness: dispatch is best-effort. ``_has_middleware()`` short-
        circuits the entire dispatch when nothing is registered, and any
        dispatch exception is caught in _hook_dispatch (never reaches the
        tool call). With no middleware, behavior is byte-identical to the
        pre-hook era (dedup + truncate only).
        """
        from harness.tools._hook_dispatch import (
            dispatch_after_tool,
            dispatch_before_tool,
        )
        from harness.tools._measure import emit_tool_output_measured
        from harness.tools._truncate import (
            _resolve_limit,
            emit_tool_output_truncated,
            truncate_tool_result,
        )
        from harness.tools.dedup_guard import get_dedup_guard

        guard = get_dedup_guard()
        is_async = iscoroutinefunction(fn)

        async def _run_and_postprocess(args, kwargs):
            """Execute the tool fn, then truncate + dispatch + measure.

            Shared by the sync and async wrappers below so the post-processing
            pipeline is defined exactly once.
            """
            # 1. PreToolUse — may block. RejectAction → short-circuit.
            reject = await dispatch_before_tool(tool_name, kwargs)
            if reject is not None:
                return f"[tool {tool_name} blocked by policy: {reject.reason}]"

            # 2. Execute (sync fns offloaded to a thread).
            if is_async:
                result = await fn(*args, **kwargs)
            else:
                import anyio
                result = await anyio.to_thread.run_sync(
                    lambda: fn(*args, **kwargs),
                )

            # 3. Truncate (existing, unconditional).
            truncated, was_cut, original_bytes = truncate_tool_result(
                tool_name, result,
            )
            if was_cut:
                emit_tool_output_truncated(
                    tool_name=tool_name,
                    original_bytes=original_bytes,
                    truncated_bytes=len(truncated.encode("utf-8"))
                    if isinstance(truncated, str) else 0,
                    limit_bytes=_resolve_limit(tool_name),
                )

            # 4. PostToolUse — may substitute or flag. Falls back to the
            #    truncated result on any error (best-effort).
            truncated = await dispatch_after_tool(tool_name, kwargs, truncated)

            # 5. Measure — emit original vs final size (bytes + tokens).
            emit_tool_output_measured(tool_name, result, truncated)
            return truncated

        if is_async:
            @wraps(fn)
            async def _async_wrapped(*args, **kwargs):
                if guard is not None and guard.check(tool_name, kwargs):
                    return f"[dedup: {tool_name} skipped — duplicate call]"
                return await _run_and_postprocess(args, kwargs)
            return _async_wrapped
        else:
            @wraps(fn)
            async def _sync_wrapped(*args, **kwargs):
                # NOTE: now async so the lifecycle dispatch (async) can run.
                # pydantic-ai accepts async tool fns; the raw sync fn is run
                # inside via anyio.to_thread (see _run_and_postprocess).
                if guard is not None and guard.check(tool_name, kwargs):
                    return f"[dedup: {tool_name} skipped — duplicate call]"
                return await _run_and_postprocess(args, kwargs)
            return _sync_wrapped


class ToolRegistry:
    """工具名 → ToolFactory 的注册表"""

    def __init__(self):
        self._factories: dict[str, ToolFactory] = {}
        self._sources: dict[str, str] = {}  # tool_name → source tag
        self._tiers: dict[str, ToolTier] = {}  # tool_name → tier

    def register(
        self,
        name: str,
        factory: ToolFactory,
        source: str = "built-in",
        tier: ToolTier = ToolTier.EXPLICIT,
    ) -> None:
        """Register a tool factory.

        Default tier is EXPLICIT (fail-safe): if a caller forgets to specify
        tier, the tool won't auto-load — protects against accidentally
        exposing heavyweight tools to every agent. Internal tools that
        should auto-load must explicitly pass tier=DEFAULT / FORCED.
        """
        self._factories[name] = factory
        self._sources[name] = source
        self._tiers[name] = tier

    def expand_globs(self, patterns: list[str], strict: bool = True) -> list[str]:
        """Expand glob patterns and ``!`` exclusions against the registry.

        Rules:
          - Literal names match themselves; must already be registered or raise
            (unless ``strict=False``).
          - ``*`` / ``?`` / ``[...]`` patterns match any subset of registered
            tool names; empty matches are allowed (no error).
          - Leading ``!`` flips the entry into an exclusion. Exclusions are
            applied last, regardless of position.
          - Output preserves input order and deduplicates.

        Args:
            strict: When True (default), unregistered literal names raise
                ToolNotFoundError. When False, they are passed through — used
                during compile() when MCP servers may not be connected yet.

        Examples:
          ["bash"]                              → ["bash"]
          ["bash", "codegraph_*"]               → ["bash", "codegraph_search", ...]
          ["bash", "codegraph_*", "!codegraph_trace"]  → all minus trace
          ["*"]                                 → every registered tool
        """
        includes: list[str] = []
        excludes: set[str] = set()
        for raw in patterns:
            if raw.startswith("!"):
                pattern = raw[1:]
                if any(c in pattern for c in "*?["):
                    excludes.update(
                        n for n in self._factories if fnmatchcase(n, pattern)
                    )
                else:
                    excludes.add(pattern)
                continue
            if any(c in raw for c in "*?["):
                for name in self._factories:
                    if fnmatchcase(name, raw) and name not in includes:
                        includes.append(name)
            else:
                if raw not in self._factories:
                    if strict:
                        raise ToolNotFoundError(f"Tool '{raw}' not registered")
                    # Non-strict: pass through unregistered names (e.g. MCP tools
                    # not yet connected). Exclusions still apply below.
                if raw not in includes:
                    includes.append(raw)
        return [n for n in includes if n not in excludes]

    def resolve(
        self,
        tool_names: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[PydanticAITool]:
        """Resolve to concrete Pydantic AI tools, applying the tier model.

        Semantics:
          - tool_names=None → load all Tier1 (FORCED) + Tier2 (DEFAULT)
            tools, minus exclude.
          - tool_names=["bash", ...] → user list + Tier1 (FORCED) tools
            (so framework-mandated tools always accompany the agent),
            minus exclude. Deduped.
          - exclude is the final authority — even FORCED tools are removed
            when listed in exclude.

        Raises ToolNotFoundError if a tool_names entry isn't registered.
        """
        exclude_set = set(exclude or [])

        if tool_names is None:
            # Default load: Tier1 + Tier2, minus exclude
            names = [
                n for n, t in self._tiers.items()
                if t in (ToolTier.FORCED, ToolTier.DEFAULT)
                and n not in exclude_set
            ]
        else:
            for name in tool_names:
                if name not in self._factories:
                    raise ToolNotFoundError(f"Tool '{name}' not registered")
            # User whitelist + forced tools, deduped, minus exclude
            user_set = set(tool_names)
            forced_extra = [
                n for n, t in self._tiers.items()
                if t == ToolTier.FORCED and n not in user_set and n not in exclude_set
            ]
            seen: set[str] = set()
            names: list[str] = []
            for n in [*tool_names, *forced_extra]:
                if n in exclude_set or n in seen:
                    continue
                seen.add(n)
                names.append(n)

        return [self._factories[n].create() for n in names]

    def list_tools(self) -> list[str]:
        return list(self._factories.keys())

    def get_tool_info(self, tool_names: list[str] | None = None) -> list[dict]:
        """Return tool name + description dicts, without resolving to PydanticAITool instances."""
        names = tool_names if tool_names is not None else list(self._factories.keys())
        result = []
        for name in names:
            factory = self._factories.get(name)
            result.append({"name": name, "description": factory.description if factory else ""})
        return result

    def get_tool_catalog(self, tool_names: list[str] | None = None) -> list[ToolCatalogEntry]:
        """Return full tool catalog entries with source and parameters."""
        names = tool_names if tool_names is not None else list(self._factories.keys())
        entries = []
        for name in names:
            factory = self._factories.get(name)
            params = {}
            if hasattr(factory, "input_schema"):
                params = factory.input_schema  # type: ignore[union-attr]
            entries.append(ToolCatalogEntry(
                name=name,
                description=factory.description if factory else "",
                source=self._sources.get(name, "unknown"),
                parameters=params,
            ))
        return entries
