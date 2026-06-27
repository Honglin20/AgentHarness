"""Tool resolution contract tests.

Validates ``resolve_tools_for_backend`` and the executor ``resolve_tools()``
methods. The resolution list is the data the frontend renders to show
"this agent uses backend X; bash → Bash (Claude built-in)".

Backend extension point: adding a new backend (opencode/codex) means
adding an ``elif backend == "..."`` branch in ``resolve_tools_for_backend``
and a matching executor ``resolve_tools()`` impl. These tests pin the
contract for the two existing backends.
"""
from __future__ import annotations

import pytest

from harness.engine.tool_resolution import (
    ToolResolution,
    resolve_tools_for_backend,
)


# ---------------------------------------------------------------------------
# pydantic-ai backend
# ---------------------------------------------------------------------------


class TestPydanticAiResolution:
    def test_all_tools_resolve_to_self(self):
        """pydantic-ai: declared == resolved, all source='pydantic-ai function'."""
        result = resolve_tools_for_backend(
            ["bash", "ask_user", "custom"], "pydantic-ai"
        )
        assert len(result) == 3
        for r in result:
            assert r.declared == r.resolved
            assert r.source == "pydantic-ai function"

    def test_empty_tools_returns_empty(self):
        assert resolve_tools_for_backend([], "pydantic-ai") == []

    def test_specific_names_preserved(self):
        """Names go through unchanged — pydantic-ai doesn't mangle."""
        result = resolve_tools_for_backend(["bash", "Bash"], "pydantic-ai")
        assert [r.declared for r in result] == ["bash", "Bash"]
        assert [r.resolved for r in result] == ["bash", "Bash"]


# ---------------------------------------------------------------------------
# claude-code backend
# ---------------------------------------------------------------------------


class TestClaudeCodeResolution:
    def test_overlapping_lowercase_maps_to_built_in(self):
        """bash/grep/glob/read_text_file → Claude PascalCase built-ins."""
        result = resolve_tools_for_backend(
            ["bash", "grep", "glob", "read_text_file"], "claude-code"
        )
        resolved_names = [r.resolved for r in result]
        assert resolved_names == ["Bash", "Grep", "Glob", "Read"]
        for r in result:
            assert r.source == "Claude built-in"

    def test_bridged_tools_get_mcp_prefix(self):
        """ask_user → mcp__harness__ask_user, source='harness MCP'."""
        result = resolve_tools_for_backend(["ask_user"], "claude-code")
        assert len(result) == 1
        r = result[0]
        assert r.declared == "ask_user"
        assert r.resolved == "mcp__harness__ask_user"
        assert r.source == "harness MCP"

    def test_explicit_mcp_prefix_passes_through(self):
        """Explicit mcp__server__name → unchanged, source='external MCP'."""
        result = resolve_tools_for_backend(
            ["mcp__other_server__tool"], "claude-code"
        )
        r = result[0]
        assert r.declared == r.resolved == "mcp__other_server__tool"
        assert r.source == "external MCP"

    def test_pascalcase_built_in_passes_through(self):
        """Bash/Read/Grep/... (PascalCase) → unchanged, source='Claude built-in'."""
        for name in ["Bash", "Read", "Edit", "Write", "Grep", "Glob",
                     "WebFetch", "WebSearch", "Task", "TodoWrite"]:
            result = resolve_tools_for_backend([name], "claude-code")
            r = result[0]
            assert r.declared == r.resolved == name
            assert r.source == "Claude built-in"

    def test_unknown_tool_marked_unknown(self):
        """Unknown tool → passthrough, source='unknown' (claude rejects at call time)."""
        result = resolve_tools_for_backend(["nonexistent_xyz"], "claude-code")
        r = result[0]
        assert r.declared == r.resolved == "nonexistent_xyz"
        assert r.source == "unknown"

    def test_mixed_tools(self):
        """Realistic NAS agent: bash + grep + sub_agent + ask_user."""
        result = resolve_tools_for_backend(
            ["bash", "grep", "sub_agent", "ask_user"], "claude-code"
        )
        # sub_agent is NOT in BRIDGED_TOOLS (per strict 2026-06-26 policy)
        # → falls through to "unknown". bash/grep → Claude built-in.
        # ask_user → harness MCP.
        by_declared = {r.declared: r for r in result}
        assert by_declared["bash"].source == "Claude built-in"
        assert by_declared["bash"].resolved == "Bash"
        assert by_declared["grep"].source == "Claude built-in"
        assert by_declared["ask_user"].source == "harness MCP"
        assert by_declared["sub_agent"].source == "unknown"

    def test_bridged_config_edit_reflected(self, monkeypatch):
        """Adding sub_agent to BRIDGED_TOOLS changes its source live.

        Operator-controlled via harness/cli_bridge_tools.py edit.
        """
        from harness.cli_bridge_tools import BRIDGED_TOOLS
        monkeypatch.setitem(BRIDGED_TOOLS, "sub_agent", "test")
        result = resolve_tools_for_backend(["sub_agent"], "claude-code")
        r = result[0]
        assert r.resolved == "mcp__harness__sub_agent"
        assert r.source == "harness MCP"


# ---------------------------------------------------------------------------
# Unknown backend (future opencode / codex before they have resolvers)
# ---------------------------------------------------------------------------


class TestUnknownBackend:
    def test_unknown_backend_marks_unknown(self):
        """Unknown backend → all tools source='unknown' (visible gap in UI)."""
        result = resolve_tools_for_backend(["bash", "ask_user"], "opencode-future")
        for r in result:
            assert r.source == "unknown"
            assert r.declared == r.resolved


# ---------------------------------------------------------------------------
# Executor instance method contract
# ---------------------------------------------------------------------------


def _make_agent_def(tools, executor="claude-code"):
    from harness.core.agent import Agent
    return Agent(name="dummy", tools=tools, executor=executor)


class TestExecutorResolveToolsMethod:
    """ClaudeCodeExecutor + LLMExecutor .resolve_tools() delegates correctly."""

    def test_claude_code_executor_delegates(self):
        from harness.engine.claude_code_executor import ClaudeCodeExecutor

        ex = ClaudeCodeExecutor(
            agent_def=_make_agent_def(["bash", "ask_user"]),
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        result = ex.resolve_tools()
        assert len(result) == 2
        # Same as resolve_tools_for_backend(claude-code) — single source of truth
        expected = resolve_tools_for_backend(["bash", "ask_user"], "claude-code")
        assert result == expected

    def test_llm_executor_delegates(self):
        from harness.engine.llm_executor import LLMExecutor

        ex = LLMExecutor(
            pydantic_agent=object(), deps=None,
            tools_declared=["bash", "ask_user"],
        )
        result = ex.resolve_tools()
        expected = resolve_tools_for_backend(["bash", "ask_user"], "pydantic-ai")
        assert result == expected

    def test_executor_returns_empty_when_no_tools(self):
        from harness.engine.claude_code_executor import ClaudeCodeExecutor
        from harness.engine.llm_executor import LLMExecutor

        # claude-code: agent_def has no tools field
        ex_cc = ClaudeCodeExecutor(
            agent_def=_make_agent_def(None),  # tools=None
            deps=None, workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        assert ex_cc.resolve_tools() == []

        # pydantic-ai: tools_declared not passed
        ex_llm = LLMExecutor(pydantic_agent=object(), deps=None)
        assert ex_llm.resolve_tools() == []


# ---------------------------------------------------------------------------
# node.started payload includes the new fields
# ---------------------------------------------------------------------------


class TestNodeStartedPayload:
    def test_includes_backend_and_tools_resolved(self):
        from harness.engine.node_phases import build_node_started_payload

        payload = build_node_started_payload(
            "wf-1", "project_analyzer", "project_analyzer",
            backend="claude-code",
            tools_resolved=[
                {"declared": "bash", "resolved": "Bash", "source": "Claude built-in"},
            ],
        )
        assert payload["backend"] == "claude-code"
        assert payload["tools_resolved"] == [
            {"declared": "bash", "resolved": "Bash", "source": "Claude built-in"},
        ]

    def test_backwards_compatible_when_omitted(self):
        """Old callers (without backend/tools_resolved args) still work.

        Fields are simply absent — old event consumers don't see them.
        """
        from harness.engine.node_phases import build_node_started_payload

        payload = build_node_started_payload("wf-1", "x", "x")
        assert "backend" not in payload
        assert "tools_resolved" not in payload
        # Core fields unchanged
        assert payload["node_id"] == "x"
        assert payload["agent_name"] == "x"
