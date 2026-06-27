"""Tool resolution config tests for claude-code executor.

Validates the post-2026-06-26 refactor contract:
  - Only tools listed in BRIDGED_TOOLS get the mcp__harness__ prefix.
  - Lowercase aliases (bash/grep/...) resolve to Claude built-ins.
  - PascalCase built-ins and explicit mcp__* pass through unchanged.
  - The mapping injection in system prompt only fires for bridged tools.
"""
from __future__ import annotations

import pytest

from harness.cli_bridge_tools import (
    BRIDGED_TOOLS,
    LOWER_TO_CLAUDE_BUILTIN,
    is_bridged,
    resolve_for_claude,
)


# ---------------------------------------------------------------------------
# resolve_for_claude — the core lookup used by _resolve_allowed_tools
# ---------------------------------------------------------------------------


class TestResolveForClaude:
    def test_bridged_tool_gets_mcp_prefix(self):
        """ask_user is in BRIDGED_TOOLS → resolves to mcp__harness__ask_user."""
        assert "ask_user" in BRIDGED_TOOLS  # sanity
        assert resolve_for_claude("ask_user") == "mcp__harness__ask_user"

    def test_lowercase_bash_maps_to_built_in(self):
        """Lowercase bash (not in BRIDGED_TOOLS) → Claude's Bash built-in."""
        assert "bash" not in BRIDGED_TOOLS
        assert resolve_for_claude("bash") == "Bash"

    def test_lowercase_read_text_file_alias_maps_to_Read(self):
        """Multiple lowercase read aliases collapse to Read."""
        assert resolve_for_claude("read_text_file") == "Read"
        assert resolve_for_claude("read_file") == "Read"
        assert resolve_for_claude("read") == "Read"

    def test_lowercase_grep_glob_edit_write(self):
        assert resolve_for_claude("grep") == "Grep"
        assert resolve_for_claude("glob") == "Glob"
        assert resolve_for_claude("edit") == "Edit"
        assert resolve_for_claude("write") == "Write"

    def test_pascalcase_built_in_passes_through(self):
        """Already-capitalized built-ins are returned unchanged."""
        assert resolve_for_claude("Bash") == "Bash"
        assert resolve_for_claude("Read") == "Read"
        assert resolve_for_claude("Grep") == "Grep"

    def test_explicit_mcp_prefix_passes_through(self):
        """Caller-pinned mcp__server__name is preserved verbatim."""
        assert resolve_for_claude("mcp__other_server__tool") == "mcp__other_server__tool"
        assert resolve_for_claude("mcp__harness__ask_user") == "mcp__harness__ask_user"

    def test_unknown_tool_passes_through_unchanged(self):
        """Unknown lowercase tools fall through; claude rejects at call time
        (fail-loud). We do NOT silently rename — operator sees the typo."""
        assert resolve_for_claude("nonexistent_tool") == "nonexistent_tool"


# ---------------------------------------------------------------------------
# Config edit → resolution reflects immediately
# ---------------------------------------------------------------------------


class TestConfigEditPropagates:
    """Adding/removing from BRIDGED_TOOLS changes resolution live.

    Operators edit the config file to control bridging — no executor
    code changes required. This test pins that contract.
    """

    def test_adding_bridged_tool_changes_resolution(self, monkeypatch):
        """After adding sub_agent to BRIDGED_TOOLS, it resolves to MCP form."""
        monkeypatch.setitem(
            BRIDGED_TOOLS, "sub_agent", "test reason"
        )
        assert resolve_for_claude("sub_agent") == "mcp__harness__sub_agent"

    def test_removing_bridged_tool_falls_back_to_passthrough(self, monkeypatch):
        """If we remove ask_user from BRIDGED_TOOLS, it no longer gets MCP prefix."""
        monkeypatch.delitem(BRIDGED_TOOLS, "ask_user")
        # Not in BRIDGED_TOOLS, not in LOWER_TO_CLAUDE_BUILTIN → passthrough
        assert resolve_for_claude("ask_user") == "ask_user"


# ---------------------------------------------------------------------------
# is_bridged helper
# ---------------------------------------------------------------------------


def test_is_bridged():
    assert is_bridged("ask_user") is True
    assert is_bridged("bash") is False
    assert is_bridged("Bash") is False
    assert is_bridged("nonexistent") is False


# ---------------------------------------------------------------------------
# ClaudeCodeExecutor integration — _resolve_allowed_tools uses the config
# ---------------------------------------------------------------------------


def _make_agent_def(tools: list[str] | None):
    class _A:
        def __init__(self, tools):
            self.name = "dummy"
            self.tools = tools
    return _A(tools)


class TestExecutorResolveAllowedTools:
    """End-to-end: ClaudeCodeExecutor._resolve_allowed_tools consumes the config."""

    def test_agent_with_only_overlapping_tools_uses_builtins(self):
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor(
            agent_def=_make_agent_def(["bash", "grep", "glob", "read_text_file"]),
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        assert ex._resolve_allowed_tools() == ["Bash", "Grep", "Glob", "Read"]

    def test_agent_with_bridged_and_overlapping(self):
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor(
            agent_def=_make_agent_def(["bash", "grep", "ask_user"]),
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        # bash → Bash (built-in), grep → Grep (built-in), ask_user → mcp__harness__
        assert ex._resolve_allowed_tools() == [
            "Bash", "Grep", "mcp__harness__ask_user",
        ]

    def test_none_tools_returns_none(self):
        """No tools declared → None (claude picks default set)."""
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor(
            agent_def=_make_agent_def(None),
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        assert ex._resolve_allowed_tools() is None

    def test_empty_tools_list_returns_none(self):
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor(
            agent_def=_make_agent_def([]),
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        assert ex._resolve_allowed_tools() is None


# ---------------------------------------------------------------------------
# System prompt tool-name injection — only fires for bridged tools
# ---------------------------------------------------------------------------


class TestRewriteBareToolNames:
    """Bare bridged tool names in the system prompt get rewritten in-place
    to their ``mcp__harness__<name>`` full form.

    Pre-refactor: a mapping block was appended, mentioning BOTH the bare
    name and the mcp__ full name → model called both → duplicate tool_use.
    Post-refactor: in-place text replacement leaves only the full name,
    eliminating the duplicate-call ambiguity (run bc2f394c).

    Non-bridged tools (bash/grep → Claude built-ins) are NOT rewritten —
    prompt literal already matches what claude exposes.
    """

    def test_no_rewrite_when_only_overlapping_tools(self):
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor(
            agent_def=_make_agent_def(["bash", "grep"]),
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        # No bridged tools → prompt untouched
        result = ex._rewrite_bare_tool_names("call bash and grep")
        assert result == "call bash and grep"

    def test_rewrite_only_bridged_tools(self):
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor(
            agent_def=_make_agent_def(["bash", "ask_user"]),
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        # ask_user is bridged → rewritten in-place; bash stays bare
        result = ex._rewrite_bare_tool_names(
            "Call `ask_user` then run `bash`."
        )
        assert "mcp__harness__ask_user" in result
        # bash is non-bridged — literal preserved (claude exposes Bash builtin)
        assert "mcp__harness__bash" not in result
        # bare ask_user must be gone (otherwise duplicate-call ambiguity returns)
        assert "`ask_user`" not in result
        # surrounding context preserved
        assert "then run `bash`" in result

    def test_rewrite_does_not_match_substring(self):
        """``ask_user_count`` must NOT be rewritten — only the standalone
        tool name token matches."""
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor(
            agent_def=_make_agent_def(["ask_user"]),
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        result = ex._rewrite_bare_tool_names(
            "Increment ask_user_count then call ask_user."
        )
        # standalone token rewritten
        assert "call mcp__harness__ask_user." in result
        # substring untouched
        assert "ask_user_count" in result
