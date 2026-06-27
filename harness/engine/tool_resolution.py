"""``ToolResolution`` — stable per-backend tool resolution contract.

When an agent runs, the framework needs to know how each declared tool name
(``bash``, ``ask_user``, ``WebFetch``...) resolves for the active backend:

  - **Claude built-in** — claude ``-p`` runs it natively; harness sees only
    the final result. ``declared="bash"`` → ``resolved="Bash"``.
  - **harness MCP** — bridged through harness MCP server
    (``mcp__harness__<name>``). Harness sees every call + result.
  - **pydantic-ai function** — in-process Python callable registered with
    the pydantic-ai Agent.
  - **passthrough** — caller knows what they're doing (explicit ``mcp__*``
    or unknown tool that the backend will reject at call time).

Each ``BaseExecutor`` subclass implements ``resolve_tools()`` returning a
list of ``ToolResolution`` (one per declared tool). The result is emitted
in ``node.started`` payloads so the frontend can render the actual
backend + tool mapping per agent.

Extensibility contract for future backends (opencode / codex / ...):

  1. Implement ``resolve_tools()`` on the new executor.
  2. Use existing ``source`` strings when they fit ("Claude built-in" /
     "harness MCP"), or introduce backend-specific ones
     ("opencode built-in", "codex native tool", ...). Frontend renders
     the source string as-is — no UI changes needed.
  3. ``declared`` and ``resolved`` are free-form strings; the frontend
     just displays them.

Stable shape: adding fields is OK; renaming/removing breaks the frontend.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResolution:
    """How one declared tool name resolves for the active backend.

    Immutable so executors can build the list once at construction time
    and share the reference safely.
    """

    #: Tool name as declared in ``workflow.json`` (e.g. ``"bash"``,
    #: ``"ask_user"``, ``"WebFetch"``). What the operator wrote.
    declared: str

    #: Tool name the backend actually sees (e.g. ``"Bash"``,
    #: ``"mcp__harness__ask_user"``, ``"WebFetch"``). Empty if backend
    #: doesn't expose the tool at all.
    resolved: str

    #: Human-readable source category. Frontend renders this verbatim.
    #: Convention: ``"<backend> built-in"`` / ``"harness MCP"`` /
    #: ``"pydantic-ai function"`` / ``"unknown"``.
    source: str

    def to_dict(self) -> dict[str, str]:
        """WS-event / JSON-serializable form."""
        return {
            "declared": self.declared,
            "resolved": self.resolved,
            "source": self.source,
        }


def resolve_tools_for_backend(
    tools: list[str],
    backend: str,
) -> list[ToolResolution]:
    """Compute ``ToolResolution`` for a list of declared tools under a backend.

    Single source of truth — used by:

      - ``LLMExecutor.resolve_tools()`` / ``ClaudeCodeExecutor.resolve_tools()``
        (instance methods on executor)
      - ``node_factory.make_node_func`` (before executor is constructed,
        so the data is ready at ``node.started`` emit time)

    Adding a new backend: add an ``elif backend == "..."`` branch below.
    Each branch owns its own resolution rules — no shared "default" past
    the final fallback so unknown backends are visible in UI as ``unknown``
    rather than silently mislabeled.

    Args:
        tools: Declared tool names (``agent_def.tools``). Empty list / None
            both return ``[]``.
        backend: Executor name (``"pydantic-ai"`` / ``"claude-code"`` /
            future). Unknown backends get the ``unknown`` fallback.

    Returns:
        ``list[ToolResolution]`` in the same order as ``tools``.
    """
    if not tools:
        return []

    if backend == "pydantic-ai":
        # pydantic-ai registers tools as Python callables on the Agent;
        # no name-mangling. ``declared == resolved``.
        return [
            ToolResolution(declared=t, resolved=t, source="pydantic-ai function")
            for t in tools
        ]

    if backend == "claude-code":
        # Lazy import to avoid module-load cycle (cli_bridge_tools is
        # independent but stay defensive for future restructuring).
        from harness.cli_bridge_tools import BRIDGED_TOOLS, LOWER_TO_CLAUDE_BUILTIN

        claude_builtins = set(LOWER_TO_CLAUDE_BUILTIN.values())
        out: list[ToolResolution] = []
        for t in tools:
            if t in BRIDGED_TOOLS:
                out.append(ToolResolution(
                    declared=t,
                    resolved=f"mcp__harness__{t}",
                    source="harness MCP",
                ))
            elif t.startswith("mcp__"):
                out.append(ToolResolution(
                    declared=t, resolved=t, source="external MCP",
                ))
            elif t in LOWER_TO_CLAUDE_BUILTIN:
                out.append(ToolResolution(
                    declared=t,
                    resolved=LOWER_TO_CLAUDE_BUILTIN[t],
                    source="Claude built-in",
                ))
            elif t in claude_builtins:
                out.append(ToolResolution(
                    declared=t, resolved=t, source="Claude built-in",
                ))
            else:
                out.append(ToolResolution(
                    declared=t, resolved=t, source="unknown",
                ))
        return out

    # Unknown backend — surface as ``unknown`` so UI shows the gap rather
    # than silently mislabelling. Once a real backend lands, replace this
    # with an explicit elif branch.
    return [
        ToolResolution(declared=t, resolved=t, source="unknown")
        for t in tools
    ]
