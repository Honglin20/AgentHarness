"""P3-T3: cli_profiles package + claude builtin profile tests."""
from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest

from harness.engine import cli_profile
from harness.engine.cli_profile import (
    CliProfile,
    disabled_profile_diagnostics,
    get_profile,
    registered_profile_names,
    reset_registry,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_registry()
    # After reset, the eager-load guard (_BUILTINS_LOADED) prevents auto
    # reload on subsequent imports. Force-load builtins here so tests see
    # the same registry state as production startup.
    from harness.cli_profiles import load_builtin_profiles
    load_builtin_profiles()
    yield
    reset_registry()


# ---------------------------------------------------------------------------
# claude builtin profile
# ---------------------------------------------------------------------------


def test_claude_builtin_profile_loads_on_import():
    """Importing harness.cli_profiles should auto-register the claude
    builtin profile via the eager load in __init__."""
    # _reset_registry fixture already calls load_builtin_profiles; just verify
    assert "claude-code" in registered_profile_names()


def test_claude_profile_fields_match_expected_flags():
    """CLAUDE_FLAGS locks the fixed claude -p invocation. Drift here would
    silently change every spawn.

    Note: ``--setting-sources project`` is intentionally NOT in profile.flags
    — it's applied conditionally by ClaudeCodeExecutor._build_spawn_config
    (only when env_overlay is non-empty, i.e. .env provided ANTHROPIC_*/CLAUDE_*).
    When .env is empty, claude falls back to ~/.claude/settings.json defaults.
    """
    profile = get_profile("claude-code")
    assert profile.flags == (
        "-p",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--strict-mcp-config",
    )
    # Setting-sources must NOT be a fixed flag (it's conditional now)
    assert "--setting-sources" not in profile.flags


def test_claude_profile_uses_minimal_paradigm():
    """claude-code must use the minimal prompt paradigm (Phase 1 fix)."""
    profile = get_profile("claude-code")
    assert profile.prompt_paradigm == "minimal"


def test_claude_profile_env_overlay_prefixes():
    """ANTHROPIC_* + CLAUDE_* extracted from .env (Phase 2 env-overlay
    contract — cli path override + token config)."""
    profile = get_profile("claude-code")
    assert "ANTHROPIC_" in profile.env_overlay_prefixes
    assert "CLAUDE_" in profile.env_overlay_prefixes


def test_claude_profile_mcp_template_renders():
    profile = get_profile("claude-code")
    args = profile.build_mcp_flag_args("/tmp/config.json")
    assert args == ("--mcp-config", "/tmp/config.json")


def test_claude_profile_delegates_translator_to_stream_json():
    """Translator must be harness.translator.translate (the stream-json
    translator that P2-T4 updated)."""
    profile = get_profile("claude-code")
    from harness.translator import translate
    assert profile.translator is translate


def test_claude_profile_delegates_extractor_to_result_extractor():
    profile = get_profile("claude-code")
    from harness.engine._result_extractor import extract_and_validate
    assert profile.result_extractor is extract_and_validate


def test_claude_profile_resolve_cli_path_uses_env_override(monkeypatch):
    monkeypatch.setenv("HARNESS_CLAUDE_CLI", "/usr/local/bin/claude-custom")
    profile = get_profile("claude-code")
    assert profile.resolve_cli_path() == "/usr/local/bin/claude-custom"


# ---------------------------------------------------------------------------
# load_builtin_profiles (idempotent)
# ---------------------------------------------------------------------------


def test_load_builtin_profiles_idempotent():
    from harness.cli_profiles import load_builtin_profiles
    n1 = load_builtin_profiles()
    n2 = load_builtin_profiles()
    # Both calls succeed; second is a no-op or refresh — registry size
    # stays the same.
    assert n1 == n2
    assert "claude-code" in registered_profile_names()


# ---------------------------------------------------------------------------
# load_project_profiles (filesystem discovery)
# ---------------------------------------------------------------------------


def test_load_project_profiles_loads_from_dir(tmp_path, monkeypatch):
    """Project-level profile discovered from <cwd>/.harness/cli_profiles/."""
    from harness.cli_profiles import load_project_profiles

    # Create a project-level profile
    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "mockcli.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        PROFILE = CliProfile(
            name="mock-cli",
            prompt_paradigm="minimal",
            cli_path_env="HARNESS_MOCK_CLI",
            default_cli_path="mock",
            flags=("--json",),
            prompt_channel="stdin",
            mcp_flag_template=None,
            env_overlay_prefixes=("MOCK_",),
            translator=lambda r, c: [],
            result_extractor=lambda t, rt: t,
        )
    """).strip())

    monkeypatch.chdir(tmp_path)
    load_project_profiles()
    assert "mock-cli" in registered_profile_names()
    assert get_profile("mock-cli").default_cli_path == "mock"


def test_project_profile_overrides_builtin(tmp_path, monkeypatch):
    """Same name = project wins (last-write-wins registration order)."""
    from harness.cli_profiles import load_builtin_profiles, load_project_profiles

    # Load builtin first
    load_builtin_profiles()
    assert get_profile("claude-code").default_cli_path == "claude"

    # Project profile claims "claude-code" but routes to a different binary
    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "claude.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        PROFILE = CliProfile(
            name="claude-code",
            prompt_paradigm="minimal",
            cli_path_env="HARNESS_CLAUDE_CLI",
            default_cli_path="/canary/claude",
            flags=("-p",),
            prompt_channel="stdin",
            mcp_flag_template=None,
            env_overlay_prefixes=("ANTHROPIC_",),
            translator=lambda r, c: [],
            result_extractor=lambda t, rt: t,
        )
    """).strip())

    monkeypatch.chdir(tmp_path)
    load_project_profiles()
    assert get_profile("claude-code").default_cli_path == "/canary/claude"


def test_disable_project_profiles_env_skips_loading(tmp_path, monkeypatch):
    """HARNESS_DISABLE_PROJECT_PROFILES=1 skips the project scan entirely."""
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "mockcli.py").write_text("PROFILE = None  # placeholder")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HARNESS_DISABLE_PROJECT_PROFILES", "1")
    n = load_project_profiles()
    assert n == 0


def test_profiles_dir_env_override(tmp_path, monkeypatch):
    """HARNESS_CLI_PROFILES_DIR redirects to a non-default location."""
    from harness.cli_profiles import load_project_profiles

    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    (custom_dir / "mockcli.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        PROFILE = CliProfile(
            name="custom-mock", prompt_paradigm="minimal",
            cli_path_env="HARNESS_MOCK_CLI", default_cli_path="mock",
            flags=(), prompt_channel="stdin",
            mcp_flag_template=None, env_overlay_prefixes=("X_",),
            translator=lambda r, c: [], result_extractor=lambda t, rt: t,
        )
    """).strip())

    monkeypatch.setenv("HARNESS_CLI_PROFILES_DIR", str(custom_dir))
    load_project_profiles(cwd=tmp_path)
    assert "custom-mock" in registered_profile_names()


def test_broken_profile_does_not_block_other_profiles(tmp_path, monkeypatch):
    """A syntax-error profile disables ONLY itself; siblings still load."""
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    # Broken module — syntax error
    (project_profiles / "broken.py").write_text("def syntax error!!!")
    # Sibling — valid
    (project_profiles / "good.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        PROFILE = CliProfile(
            name="good-cli", prompt_paradigm="minimal",
            cli_path_env="HARNESS_GOOD_CLI", default_cli_path="good",
            flags=(), prompt_channel="stdin",
            mcp_flag_template=None, env_overlay_prefixes=("G_",),
            translator=lambda r, c: [], result_extractor=lambda t, rt: t,
        )
    """).strip())

    monkeypatch.chdir(tmp_path)
    n = load_project_profiles()
    assert n == 1  # only "good" registered
    assert "good-cli" in registered_profile_names()
    # "broken" is in registry as disabled
    assert "broken" in disabled_profile_diagnostics()
    # Using broken profile fails with the disable reason
    with pytest.raises(ValueError, match="disabled"):
        get_profile("broken")


def test_missing_profile_attr_disables_filename_stem(tmp_path, monkeypatch):
    """A module that doesn't export PROFILE gets disabled by filename stem."""
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "noprobe.py").write_text("# no PROFILE export")

    monkeypatch.chdir(tmp_path)
    load_project_profiles()
    assert "noprobe" in disabled_profile_diagnostics()
