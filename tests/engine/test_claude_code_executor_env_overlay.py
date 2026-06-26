"""P3-T7: profile-aware env overlay tests."""
from __future__ import annotations

import pytest

from harness.engine.claude_code_executor import ClaudeCodeExecutor
from harness.engine.cli_profile import CliProfile
from harness.core.agent import Agent


def _make_profile(name="claude-code", prefixes=("ANTHROPIC_", "CLAUDE_")):
    from harness.translator import translate
    from harness.engine._result_extractor import extract_and_validate
    return CliProfile(
        name=name,
        prompt_paradigm="minimal",
        cli_path_env="HARNESS_CLAUDE_CLI",
        default_cli_path="claude",
        flags=(),
        prompt_channel="stdin",
        mcp_flag_template=None,
        env_overlay_prefixes=prefixes,
        translator=translate,
        result_extractor=extract_and_validate,
    )


def _make_executor(profile):
    return ClaudeCodeExecutor(
        agent_def=Agent("x"), deps=None,
        workflow_id="w", node_id="x", agent_name="x",
        enable_mcp=False, profile=profile,
    )


def test_overlay_uses_profile_prefixes(monkeypatch, tmp_path):
    """Only keys matching profile.env_overlay_prefixes are extracted."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_AUTH_TOKEN=secret\n"
        "ANTHROPIC_BASE_URL=https://api.x.com\n"
        "CLAUDE_MODEL=claude-sonnet-4-6\n"
        "OPENCODE_TOKEN=should-not-leak\n"  # not in claude profile prefixes
        "HARNESS_API_KEY=should-not-leak\n"
    )
    monkeypatch.setattr("harness.paths.get_env_file", lambda: env_file)
    ex = _make_executor(_make_profile(prefixes=("ANTHROPIC_", "CLAUDE_")))
    overlay = ex._load_env_overlay()
    assert overlay["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert overlay["ANTHROPIC_BASE_URL"] == "https://api.x.com"
    assert overlay["CLAUDE_MODEL"] == "claude-sonnet-4-6"
    assert "OPENCODE_TOKEN" not in overlay
    assert "HARNESS_API_KEY" not in overlay


def test_overlay_changes_with_profile_prefixes(monkeypatch, tmp_path):
    """Switching to an opencode-style profile extracts OPENCODE_* instead."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_AUTH_TOKEN=anthropic-secret\n"
        "OPENCODE_TOKEN=opencode-secret\n"
        "OPENCODE_BASE_URL=https://opencode.dev\n"
    )
    monkeypatch.setattr("harness.paths.get_env_file", lambda: env_file)
    opencode_profile = _make_profile(
        name="opencode", prefixes=("OPENCODE_",),
    )
    ex = _make_executor(opencode_profile)
    overlay = ex._load_env_overlay()
    assert overlay == {
        "OPENCODE_TOKEN": "opencode-secret",
        "OPENCODE_BASE_URL": "https://opencode.dev",
    }


def test_per_profile_env_var_override_wins(monkeypatch, tmp_path):
    """HARNESS_CLAUDE_CODE_ENV_<KEY>=val overrides .env value.

    Lets operators do canary tests without editing the project .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_BASE_URL=https://default.example.com\n")
    monkeypatch.setattr("harness.paths.get_env_file", lambda: env_file)
    monkeypatch.setenv(
        "HARNESS_CLAUDE_CODE_ENV_ANTHROPIC_BASE_URL",
        "https://canary.example.com",
    )
    ex = _make_executor(_make_profile())
    overlay = ex._load_env_overlay()
    assert overlay["ANTHROPIC_BASE_URL"] == "https://canary.example.com"


def test_per_profile_env_var_injects_new_key(monkeypatch, tmp_path):
    """HARNESS_<NAME>_ENV_<KEY> can inject keys that aren't in .env at all."""
    env_file = tmp_path / ".env"
    env_file.write_text("# empty\n")
    monkeypatch.setattr("harness.paths.get_env_file", lambda: env_file)
    monkeypatch.setenv("HARNESS_CLAUDE_CODE_ENV_DEBUG_LOG", "verbose")
    ex = _make_executor(_make_profile())
    overlay = ex._load_env_overlay()
    assert overlay["DEBUG_LOG"] == "verbose"


def test_per_profile_env_var_only_matches_its_own_profile(monkeypatch, tmp_path):
    """HARNESS_OPENCODE_ENV_X must NOT leak into claude-code's overlay
    (and vice versa)."""
    env_file = tmp_path / ".env"
    env_file.write_text("# empty\n")
    monkeypatch.setattr("harness.paths.get_env_file", lambda: env_file)
    monkeypatch.setenv("HARNESS_OPENCODE_ENV_OPENCODE_TOKEN", "oc-token")
    monkeypatch.setenv("HARNESS_CLAUDE_CODE_ENV_ANTHROPIC_TOKEN", "cl-token")

    claude_ex = _make_executor(_make_profile(name="claude-code"))
    claude_overlay = claude_ex._load_env_overlay()
    assert claude_overlay.get("ANTHROPIC_TOKEN") == "cl-token"
    assert "OPENCODE_TOKEN" not in claude_overlay
