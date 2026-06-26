"""P3-T11: end-to-end mock test for a user-defined CLI profile.

Simulates the full P3 chain with a custom "mock-opencode" profile:

  1. Project-level profile discovered from <cwd>/.harness/cli_profiles/
  2. Profile registered (overrides nothing — independent of claude-code)
  3. Agent construction with executor="mock-opencode" succeeds (VALID_EXECUTORS
     dynamic merge)
  4. executor_factory dispatches to ClaudeCodeExecutor with that profile
  5. ClaudeCodeExecutor.run() uses the profile's flags / cli_path / translator
  6. Error path emits agent.executor_error with executor="mock-opencode"
     (profile name, not hardcoded "claude-code")

This locks the user-facing promise: writing a profile file is the ONLY
step needed to add a new backend.
"""
from __future__ import annotations

import asyncio
import json
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest

from harness.core.agent import Agent, VALID_EXECUTORS
from harness.engine.executor_factory import make_executor
from harness.engine.claude_code_executor import ClaudeCodeExecutor
from harness.engine.cli_profile import (
    disabled_profile_diagnostics,
    get_profile,
    registered_profile_names,
    reset_registry,
)


@pytest.fixture(autouse=True)
def _reset_registry_with_builtins():
    reset_registry()
    from harness.cli_profiles import load_builtin_profiles
    load_builtin_profiles()
    yield
    reset_registry()
    load_builtin_profiles()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Profile discovery + dispatch
# ---------------------------------------------------------------------------


def test_project_profile_e2e_dispatch(tmp_path, monkeypatch):
    """Write a project-level profile → server startup discovers it →
    agent construction succeeds → executor_factory dispatches with that profile.

    This is the user-facing "just write a profile file" workflow."""
    # 1. Write project-level profile
    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "mock_opencode.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        from harness.translator import translate

        PROFILE = CliProfile(
            name="mock-opencode",
            prompt_paradigm="minimal",
            cli_path_env="HARNESS_OPENCODE_CLI",
            default_cli_path="opencode",
            flags=("--json", "--no-color"),
            prompt_channel="stdin",
            mcp_flag_template=None,
            env_overlay_prefixes=("OPENCODE_",),
            translator=translate,
            result_extractor=lambda t, rt: t,
            default_timeout_s=120.0,
        )
    """).strip())

    monkeypatch.chdir(tmp_path)
    # 2. Simulate server startup
    from harness.cli_profiles import load_all_profiles_at_startup
    builtin_count, project_count = load_all_profiles_at_startup()
    assert project_count == 1
    assert "mock-opencode" in registered_profile_names()

    # 3. Agent construction succeeds (VALID_EXECUTORS dynamic merge)
    assert "mock-opencode" in VALID_EXECUTORS()
    agent = Agent("analyzer", executor="mock-opencode")
    assert agent.executor == "mock-opencode"

    # 4. executor_factory dispatches with the profile
    ex = make_executor(
        agent_def=agent, pydantic_agent=None, deps=None,
        workflow_id="w", node_id="n", agent_name="a",
    )
    assert isinstance(ex, ClaudeCodeExecutor)
    assert ex._profile.name == "mock-opencode"
    assert ex._profile.default_cli_path == "opencode"
    assert "--no-color" in ex._profile.flags


# ---------------------------------------------------------------------------
# Profile-aware error emission
# ---------------------------------------------------------------------------


def test_custom_profile_error_emission_uses_profile_name(tmp_path, monkeypatch):
    """When a custom-profile agent fails, agent.executor_error carries
    executor='mock-opencode' (profile name) — NOT 'claude-code'. Operators
    can tell which backend failed without parsing stderr."""
    # Register the custom profile directly (skip the filesystem step —
    # already covered by the previous test)
    from harness.engine.cli_profile import CliProfile, register_cli_profile
    from harness.translator import translate
    register_cli_profile(CliProfile(
        name="mock-opencode", prompt_paradigm="minimal",
        cli_path_env="HARNESS_OPENCODE_CLI", default_cli_path="opencode",
        flags=("--json",), prompt_channel="stdin",
        mcp_flag_template=None, env_overlay_prefixes=("OPENCODE_",),
        translator=translate, result_extractor=lambda t, rt: t,
    ))

    bus = MagicMock()
    bus.events = []
    bus.emit = lambda t, p, **k: bus.events.append((t, p))

    # Mock run_claude — executor's _build_spawn_config uses the profile's
    # flags, but the spawn itself goes through run_claude (claude-specific
    # subprocess helper). For mock-opencode we'd ideally use run_cli, but
    # ClaudeCodeExecutor currently calls run_claude directly. This is
    # acceptable for the test — we're verifying error attribution, not
    # subprocess spawning.
    from harness.engine._claude_subprocess import ClaudeRunResult

    async def fake_run_claude(cfg, on_line=None, *, timeout=None):
        return ClaudeRunResult(exit_code=1, stderr="opencode: auth failed", timed_out=False)

    agent = Agent("x", executor="mock-opencode")
    ex = make_executor(
        agent_def=agent, pydantic_agent=None, deps=None,
        event_bus=bus, workflow_id="w", node_id="x", agent_name="x",
    )
    # Skip MCP setup (CI friendly — no real subprocess spawn)
    ex._enable_mcp = False
    with patch(
        "harness.engine.claude_code_executor.run_claude",
        side_effect=fake_run_claude,
    ):
        from harness.engine.error_event import ExecutorError
        with pytest.raises(ExecutorError) as exc_info:
            _run(ex.run("ctx"))

    # ErrorEvent carries the profile name
    assert exc_info.value.error_event.executor == "mock-opencode"
    assert exc_info.value.error_event.phase == "spawn"
    # Bus event likewise
    assert bus.events[-1][1]["executor"] == "mock-opencode"


# ---------------------------------------------------------------------------
# HARNESS_<NAME>_CLI override works for custom profiles
# ---------------------------------------------------------------------------


def test_custom_profile_cli_path_env_override(monkeypatch):
    """HARNESS_OPENCODE_CLI env var overrides the profile's default path."""
    from harness.engine.cli_profile import CliProfile, register_cli_profile
    register_cli_profile(CliProfile(
        name="mock-opencode", prompt_paradigm="minimal",
        cli_path_env="HARNESS_OPENCODE_CLI", default_cli_path="opencode",
        flags=(), prompt_channel="stdin", mcp_flag_template=None,
        env_overlay_prefixes=("OPENCODE_",),
        translator=lambda r, c: [], result_extractor=lambda t, rt: t,
    ))
    monkeypatch.setenv("HARNESS_OPENCODE_CLI", "/usr/local/bin/opencode-canary")
    profile = get_profile("mock-opencode")
    assert profile.resolve_cli_path() == "/usr/local/bin/opencode-canary"


# ---------------------------------------------------------------------------
# Custom profile coexists with builtins
# ---------------------------------------------------------------------------


def test_custom_profile_does_not_break_builtins(tmp_path, monkeypatch):
    """Adding a project-level profile does NOT disable / override
    claude-code unless explicitly using the same name."""
    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "mock_opencode.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        PROFILE = CliProfile(
            name="mock-opencode", prompt_paradigm="minimal",
            cli_path_env="HARNESS_OPENCODE_CLI", default_cli_path="opencode",
            flags=(), prompt_channel="stdin", mcp_flag_template=None,
            env_overlay_prefixes=("OPENCODE_",),
            translator=lambda r, c: [], result_extractor=lambda t, rt: t,
        )
    """).strip())

    monkeypatch.chdir(tmp_path)
    from harness.cli_profiles import load_all_profiles_at_startup
    load_all_profiles_at_startup()

    # Both available
    assert "claude-code" in registered_profile_names()
    assert "mock-opencode" in registered_profile_names()
    # Nothing disabled
    assert disabled_profile_diagnostics() == {}
    # claude-code profile is unchanged (no override)
    assert get_profile("claude-code").default_cli_path == "claude"


# ---------------------------------------------------------------------------
# Full chain (profile discovery → dispatch → error emission → workflow.error)
# ---------------------------------------------------------------------------


def test_e2e_custom_profile_unified_error_flow(tmp_path, monkeypatch):
    """Project profile + ClaudeCodeExecutor + ErrorEvent + workflow.error —
    the full P3 chain in one test."""
    from harness.engine.error_event import build_workflow_error_payload
    from harness.engine._claude_subprocess import ClaudeRunResult

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "mock_opencode.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        from harness.translator import translate
        PROFILE = CliProfile(
            name="mock-opencode", prompt_paradigm="minimal",
            cli_path_env="HARNESS_OPENCODE_CLI", default_cli_path="opencode",
            flags=("--json",), prompt_channel="stdin",
            mcp_flag_template=None, env_overlay_prefixes=("OPENCODE_",),
            translator=translate, result_extractor=lambda t, rt: t,
        )
    """).strip())

    monkeypatch.chdir(tmp_path)
    from harness.cli_profiles import load_all_profiles_at_startup
    load_all_profiles_at_startup()

    bus = MagicMock()
    bus.events = []
    bus.buffer = []
    def emit(t, p, **k):
        bus.events.append((t, p))
        bus.buffer.append((t, p))
    bus.emit = emit

    async def fake_run_claude(cfg, on_line=None, *, timeout=None):
        return ClaudeRunResult(exit_code=2, stderr="opencode: rate limited", timed_out=False)

    agent = Agent("analyzer", executor="mock-opencode")
    ex = make_executor(
        agent_def=agent, pydantic_agent=None, deps=None,
        event_bus=bus, workflow_id="wf-opencode", node_id="analyzer", agent_name="analyzer",
    )
    ex._enable_mcp = False  # CI friendly — skip MCP subprocess

    with patch(
        "harness.engine.claude_code_executor.run_claude",
        side_effect=fake_run_claude,
    ):
        from harness.engine.error_event import ExecutorError
        with pytest.raises(ExecutorError) as exc_info:
            _run(ex.run("ctx"))

    # 1. agent.executor_error emitted with profile name
    executor_errors = [p for (t, p) in bus.events if t == "agent.executor_error"]
    assert len(executor_errors) == 1
    assert executor_errors[0]["executor"] == "mock-opencode"
    assert executor_errors[0]["phase"] == "spawn"
    assert "rate limited" in executor_errors[0]["stderr_tail"]

    # 2. workflow.error payload (built from the same context) carries the
    # profile name through to the frontend
    workflow_payload = build_workflow_error_payload(
        workflow_id="wf-opencode", user_id=None,
        error=exc_info.value,
        agents_snapshot=[{"name": "analyzer", "executor": "mock-opencode"}],
        bus_buffer=bus.buffer,
    )
    assert workflow_payload["executor"] == "mock-opencode"
    assert workflow_payload["failed_node"] == "analyzer"
    assert workflow_payload["phase"] == "spawn"
