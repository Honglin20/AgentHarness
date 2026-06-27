"""Config: which harness tools to bridge to ``claude -p`` via MCP.

When ``claude-code`` is the executor, each agent's declared ``tools`` are
resolved at spawn time into a ``--allowed-tools`` allowlist passed to the
claude subprocess. Resolution rules (in order):

  1. ``mcp__*`` already                    → pass through verbatim
                                              (caller pinned a specific server)

  2. Tool listed in ``BRIDGED_TOOLS`` below → expose via harness MCP as
                                              ``mcp__harness__<name>``.
                                              Harness Python impl runs;
                                              harness sees every call + result.

  3. PascalCase Claude built-in            → pass through verbatim
                                              (``Bash``, ``Read``, ``Grep``...)

  4. Lowercase alias in ``LOWER_TO_CLAUDE_BUILTIN``
                                           → mapped to the PascalCase built-in.
                                              Claude runs it directly; harness
                                              does NOT see individual calls.

  5. Anything else                         → passed through; claude will reject
                                              at call time (fail-loud).

Why this design (post-2026-06-26 refactor):

  - Pre-refactor: every lowercase tool was bridged via harness MCP. This
    gave harness full visibility (UI streaming, replay, rate limits, token
    accounting) but duplicated work Claude could do natively. ``bash`` via
    MCP is functionally identical to Claude's ``Bash`` built-in — the only
    difference is who sees the call.

  - Post-refactor: default is to **trust Claude's built-ins**. Harness only
    bridges when (a) Claude has no equivalent, OR (b) the harness version
    is explicitly required (e.g. ``ask_user`` replaces ``AskUserQuestion``
    which is broken in ``-p`` mode — returns placeholder strings).

Adding a new bridged tool:

  1. Append to ``BRIDGED_TOOLS`` below with a short reason.
  2. Ensure ``harness/mcp/`` actually exposes it (see ``harness/tools/``).
  3. Re-run ``tests/engine/test_claude_code_executor_profile.py`` and the
     tool-resolution test in ``tests/engine/test_cli_bridge_tools.py``.

Removing a bridged tool (delegate to Claude built-in):

  1. Delete the entry from ``BRIDGED_TOOLS``.
  2. If agents still reference it by lowercase name, add a lowercase→built-in
     alias to ``LOWER_TO_CLAUDE_BUILTIN`` so the legacy name keeps working.
"""
from __future__ import annotations


#: Tools bridged to harness MCP regardless of Claude built-in availability.
#: Each value is a short reason explaining WHY we bridge instead of letting
#: Claude's built-in handle it. Reasons help future maintainers decide whether
#: the bridge is still needed.
#:
#: Current policy (per operator directive 2026-06-26): bridge only ``ask_user``.
#: ``sub_agent`` and ``render_chart`` (Claude has no equivalent) are intentionally
#: NOT bridged yet — operators will add them here when a workflow requires them.
BRIDGED_TOOLS: dict[str, str] = {
    "ask_user": (
        "Replaces Claude's AskUserQuestion. In -p mode AskUserQuestion cannot "
        "spawn UI and returns a placeholder string, causing the model to "
        "hallucinate user input. Harness's ask_user routes through the WS "
        "BLOCK chain and surfaces a real AgentQuestionCard to the operator."
    ),
}


#: Lowercase harness alias → Claude Code built-in canonical name.
#:
#: When an agent declares a tool by lowercase name AND it is NOT in
#: ``BRIDGED_TOOLS`` above, this mapping decides which Claude built-in to
#: expose instead. Names not in this map and not in ``BRIDGED_TOOLS`` fall
#: through to claude as-is (which will reject unknown tools at call time).
#:
#: Add entries here when:
#:   - A workflow uses the lowercase harness name but you've removed the
#:     bridge entry and want seamless fallback to Claude's built-in.
#:   - Multiple lowercase aliases should resolve to the same built-in
#:     (e.g. ``read_text_file`` and ``read_file`` both → ``Read``).
LOWER_TO_CLAUDE_BUILTIN: dict[str, str] = {
    "bash": "Bash",
    "read": "Read",
    "read_text_file": "Read",
    "read_file": "Read",
    "edit": "Edit",
    "write": "Write",
    "grep": "Grep",
    "glob": "Glob",
    "webfetch": "WebFetch",
    "websearch": "WebSearch",
    "task": "Task",
    "todowrite": "TodoWrite",
}


def is_bridged(tool_name: str) -> bool:
    """Return True iff ``tool_name`` should be exposed via harness MCP."""
    return tool_name in BRIDGED_TOOLS


def resolve_for_claude(tool_name: str) -> str:
    """Resolve a declared tool name to its ``--allowed-tools`` form.

    Returns one of:
      - ``mcp__<server>__<name>``  — bridged through harness MCP
      - ``Bash`` / ``Read`` / ...  — Claude built-in canonical name
      - the input unchanged        — caller knows what they're doing OR
                                     unknown tool (claude will reject)
    """
    if tool_name.startswith("mcp__"):
        return tool_name
    if tool_name in BRIDGED_TOOLS:
        return f"mcp__harness__{tool_name}"
    if tool_name in LOWER_TO_CLAUDE_BUILTIN:
        return LOWER_TO_CLAUDE_BUILTIN[tool_name]
    return tool_name
