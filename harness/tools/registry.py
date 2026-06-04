from abc import ABC, abstractmethod
from asyncio import iscoroutinefunction
from fnmatch import fnmatchcase
from functools import wraps

from pydantic_ai import Tool as PydanticAITool


class ToolNotFoundError(Exception):
    pass


class ToolFactory(ABC):
    """Abstract tool factory — subclasses must implement create()."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def create(self) -> PydanticAITool: ...

    def _wrap_fn(self, fn, tool_name: str):
        """Wrap a tool function with dedup guard if configured.

        Preserves sync/async nature of the original function.
        """
        from harness.tools.dedup_guard import get_dedup_guard

        guard = get_dedup_guard()
        if guard is None:
            return fn

        if iscoroutinefunction(fn):
            @wraps(fn)
            async def _async_wrapped(*args, **kwargs):
                if guard.check(tool_name, kwargs):
                    return f"[dedup: {tool_name} skipped — duplicate call]"
                return await fn(*args, **kwargs)
            return _async_wrapped
        else:
            @wraps(fn)
            def _sync_wrapped(*args, **kwargs):
                if guard.check(tool_name, kwargs):
                    return f"[dedup: {tool_name} skipped — duplicate call]"
                return fn(*args, **kwargs)
            return _sync_wrapped


class ToolRegistry:
    """工具名 → ToolFactory 的注册表"""

    def __init__(self):
        self._factories: dict[str, ToolFactory] = {}

    def register(self, name: str, factory: ToolFactory) -> None:
        self._factories[name] = factory

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
        exclude_set = set(exclude or [])

        if tool_names is None:
            names = [n for n in self._factories if n not in exclude_set]
        else:
            for name in tool_names:
                if name not in self._factories:
                    raise ToolNotFoundError(f"Tool '{name}' not registered")
            names = [n for n in tool_names if n not in exclude_set]

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
