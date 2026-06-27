"""P3-T4: ClaudeCodeExecutor profile-driven behaviour tests.

Locks the contract that ClaudeCodeExecutor reads its CLI configuration
from a CliProfile instead of hardcoded values. Operators can pass a
custom profile (e.g. canary claude build) without touching executor code.
"""
from __future__ import annotations

import asyncio

import pytest

from harness.engine.claude_code_executor import ClaudeCodeExecutor
from harness.engine.cli_profile import CliProfile
from harness.core.agent import Agent


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_profile(name="claude-code", **overrides):
    """Build a profile matching the real claude builtin structure."""
    from harness.translator import translate
    from harness.engine._result_extractor import extract_and_validate
    defaults = dict(
        name=name,
        prompt_paradigm="minimal",
        cli_path_env="HARNESS_CLAUDE_CLI",
        default_cli_path="claude",
        flags=("-p",),
        prompt_channel="stdin",
        mcp_flag_template="--mcp-config {path}",
        env_overlay_prefixes=("ANTHROPIC_", "CLAUDE_"),
        translator=translate,
        result_extractor=extract_and_validate,
    )
    defaults.update(overrides)
    return CliProfile(**defaults)


def test_default_profile_resolved_from_registry():
    """No profile kwarg → ClaudeCodeExecutor resolves "claude-code" from
    the registry (loaded by tests/conftest.py)."""
    ex = ClaudeCodeExecutor(
        agent_def=Agent("x"), deps=None,
        workflow_id="w", node_id="x", agent_name="x",
        enable_mcp=False,
    )
    assert ex._profile.name == "claude-code"


def test_explicit_profile_overrides_registry():
    """Passing profile= bypasses the registry lookup — canary support."""
    canary = _make_profile(default_cli_path="/canary/claude")
    ex = ClaudeCodeExecutor(
        agent_def=Agent("x"), deps=None,
        workflow_id="w", node_id="x", agent_name="x",
        enable_mcp=False,
        profile=canary,
    )
    assert ex._profile is canary
    assert ex._profile.default_cli_path == "/canary/claude"


def test_executor_error_payload_uses_profile_name():
    """ErrorEvent.executor must reflect the profile name, not hardcoded
    "claude-code". Lets operators see which profile was active when a
    canary profile fails."""
    from unittest.mock import MagicMock, patch
    from harness.engine._claude_subprocess import ClaudeRunResult
    from harness.engine.error_event import ExecutorError

    canary = _make_profile(name="claude-canary")
    bus = MagicMock()
    bus.events = []
    bus.emit = lambda t, p, **k: bus.events.append((t, p))

    async def fake_run_claude(cfg, on_line=None, *, timeout=None):
        return ClaudeRunResult(exit_code=1, stderr="boom", timed_out=False)

    ex = ClaudeCodeExecutor(
        agent_def=Agent("x"), deps=None,
        event_bus=bus, workflow_id="w", node_id="x", agent_name="x",
        enable_mcp=False, profile=canary,
    )
    with patch(
        "harness.engine.claude_code_executor.run_claude",
        side_effect=fake_run_claude,
    ):
        with pytest.raises(ExecutorError) as exc_info:
            _run(ex.run("ctx"))
    # ErrorEvent carries profile name, not hardcoded
    assert exc_info.value.error_event.executor == "claude-canary"
    # Bus event likewise
    assert bus.events[-1][1]["executor"] == "claude-canary"


def test_missing_builtin_profile_self_heals_then_raises_if_loader_broken(monkeypatch):
    """Self-heal contract: empty registry triggers lazy builtin load on
    first get_profile call. ClaudeCodeExecutor(profile=None) succeeds
    because the lazy load fills the registry.

    Regression for the stale-server bug: a server started before P3-T8
    never called load_all_profiles_at_startup in lifespan, leaving the
    registry empty. Without self-heal, ClaudeCodeExecutor construction
    would fail with a confusing KeyError. With self-heal, the first
    access repopulates the registry transparently.
    """
    from harness.engine.cli_profile import reset_registry
    import harness.engine.cli_profile as cp_mod
    reset_registry()
    assert not cp_mod._BUILTINS_AUTO_LOADED, "reset_registry must re-arm the auto-load flag"
    try:
        # Construction succeeds — self-heal loads claude-code on first lookup.
        ex = ClaudeCodeExecutor(
            agent_def=Agent("x"), deps=None,
            workflow_id="w", node_id="x", agent_name="x",
            enable_mcp=False,
        )
        assert ex._profile.name == "claude-code"
        assert cp_mod._BUILTINS_AUTO_LOADED, "auto-load flag must be set after first lookup"

        # If the loader is genuinely broken (e.g. corrupt profile module),
        # the same construction surfaces a clear RuntimeError pointing at
        # the fix — defensive contract for operators.
        reset_registry()

        def _force_load_fail():
            # Set the flag so the real impl doesn't run, leaving registry empty.
            cp_mod._BUILTINS_AUTO_LOADED = True

        monkeypatch.setattr(cp_mod, "_auto_load_builtins_if_needed", _force_load_fail)
        with pytest.raises(RuntimeError, match="requires 'claude-code' profile"):
            ClaudeCodeExecutor(
                agent_def=Agent("x"), deps=None,
                workflow_id="w", node_id="x", agent_name="x",
                enable_mcp=False,
            )
    finally:
        # Restore registry + flag for other tests
        monkeypatch.undo()
        reset_registry()
        from harness.cli_profiles import load_builtin_profiles
        load_builtin_profiles()


def test_profile_extractor_used_for_schema_validation():
    """When agent_def.result_type is custom, _extract_and_validate_result
    delegates to profile.result_extractor (not the global function)."""
    from pydantic import BaseModel
    from unittest.mock import MagicMock, patch
    from harness.engine._claude_subprocess import ClaudeRunResult
    from harness.engine.error_event import ExecutorError

    class _Custom(BaseModel):
        summary: str

    extractor_calls: list = []

    def recording_extractor(text, result_type):
        extractor_calls.append((text, result_type))
        return result_type(summary=text)

    custom_profile = _make_profile(result_extractor=recording_extractor)
    bus = MagicMock()
    bus.events = []
    bus.emit = lambda t, p, **k: bus.events.append((t, p))

    async def fake_run_claude(cfg, on_line=None, *, timeout=None):
        if on_line:
            import json
            await on_line(json.dumps({
                "type": "result", "is_error": False,
                "duration_ms": 1, "result": '{"summary": "ok"}',
                "usage": {},
            }))
        return ClaudeRunResult(exit_code=0, stderr="", timed_out=False)

    ex = ClaudeCodeExecutor(
        agent_def=Agent("x", result_type=_Custom), deps=None,
        event_bus=bus, workflow_id="w", node_id="x", agent_name="x",
        enable_mcp=False, profile=custom_profile,
    )
    with patch(
        "harness.engine.claude_code_executor.run_claude",
        side_effect=fake_run_claude,
    ):
        result = _run(ex.run("ctx"))
    # Profile's recording_extractor was invoked with raw text + result_type
    assert len(extractor_calls) == 1
    assert extractor_calls[0][1] is _Custom
    assert isinstance(result.agent_run.result.output, _Custom)
