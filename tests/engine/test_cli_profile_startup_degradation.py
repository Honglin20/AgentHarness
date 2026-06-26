"""P3-T9: graceful degradation for broken / disabled profiles.

Verifies the contract documented in harness/cli_profiles/__init__.py:
  - HARNESS_DISABLE_PROJECT_PROFILES=1 skips project-level scan
  - Broken profile (syntax error / missing PROFILE) → disable_profile +
    startup continues; other profiles still load
  - Using a disabled profile raises clear ValueError at construction
  - Startup log lists disabled profiles so operators see the failure
"""
from __future__ import annotations

from textwrap import dedent

import pytest

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


# ---------------------------------------------------------------------------
# HARNESS_DISABLE_PROJECT_PROFILES=1
# ---------------------------------------------------------------------------


def test_disable_env_skips_project_scan(tmp_path, monkeypatch):
    """HARNESS_DISABLE_PROJECT_PROFILES=1 → load_project_profiles returns 0
    and does not touch the registry even if valid profiles exist."""
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "valid.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        PROFILE = CliProfile(
            name="valid-cli", prompt_paradigm="minimal",
            cli_path_env="HARNESS_VALID_CLI", default_cli_path="v",
            flags=(), prompt_channel="stdin", mcp_flag_template=None,
            env_overlay_prefixes=("X",),
            translator=lambda r, c: [], result_extractor=lambda t, rt: t,
        )
    """).strip())

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HARNESS_DISABLE_PROJECT_PROFILES", "1")
    n = load_project_profiles()
    assert n == 0
    assert "valid-cli" not in registered_profile_names()


# ---------------------------------------------------------------------------
# Broken profile modules disable themselves but siblings still load
# ---------------------------------------------------------------------------


def test_syntax_error_profile_disables_itself(tmp_path, monkeypatch):
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "syntaxerr.py").write_text("def !!! broken")
    monkeypatch.chdir(tmp_path)
    load_project_profiles()
    diag = disabled_profile_diagnostics()
    assert "syntaxerr" in diag
    # Reason carries the actual SyntaxError so operators can fix without
    # digging into logs
    assert "SyntaxError" in diag["syntaxerr"]


def test_missing_profile_attr_disables_filename_stem(tmp_path, monkeypatch):
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "noattr.py").write_text("# no PROFILE export")
    monkeypatch.chdir(tmp_path)
    load_project_profiles()
    assert "noattr" in disabled_profile_diagnostics()


def test_profile_attr_wrong_type_disables(tmp_path, monkeypatch):
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "wrongtype.py").write_text("PROFILE = 'not a CliProfile'")
    monkeypatch.chdir(tmp_path)
    load_project_profiles()
    assert "wrongtype" in disabled_profile_diagnostics()


def test_broken_profile_does_not_block_valid_sibling(tmp_path, monkeypatch):
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "broken.py").write_text("raise RuntimeError('boom')")
    (project_profiles / "good.py").write_text(dedent("""
        from harness.engine.cli_profile import CliProfile
        PROFILE = CliProfile(
            name="good-cli", prompt_paradigm="minimal",
            cli_path_env="HARNESS_GOOD_CLI", default_cli_path="good",
            flags=(), prompt_channel="stdin", mcp_flag_template=None,
            env_overlay_prefixes=("X",),
            translator=lambda r, c: [], result_extractor=lambda t, rt: t,
        )
    """).strip())
    monkeypatch.chdir(tmp_path)
    n = load_project_profiles()
    assert n == 1
    assert "good-cli" in registered_profile_names()
    assert "broken" in disabled_profile_diagnostics()


# ---------------------------------------------------------------------------
# Using a disabled profile raises clear error
# ---------------------------------------------------------------------------


def test_using_disabled_profile_raises_with_reason(tmp_path, monkeypatch):
    from harness.cli_profiles import load_project_profiles

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "broken.py").write_text("raise ImportError('missing dep')")
    monkeypatch.chdir(tmp_path)
    load_project_profiles()

    with pytest.raises(ValueError, match="disabled.*missing dep"):
        get_profile("broken")


# ---------------------------------------------------------------------------
# Startup-level graceful degradation
# ---------------------------------------------------------------------------


def test_load_all_profiles_at_startup_continues_on_broken(tmp_path, monkeypatch):
    """load_all_profiles_at_startup must not raise even if a profile is
    broken — the broken one disables itself and the function returns
    counts (including 0 for the broken one)."""
    from harness.cli_profiles import load_all_profiles_at_startup

    project_profiles = tmp_path / ".harness/cli_profiles"
    project_profiles.mkdir(parents=True)
    (project_profiles / "broken.py").write_text("syntax !!! error")
    monkeypatch.chdir(tmp_path)

    builtin_count, project_count = load_all_profiles_at_startup()
    assert builtin_count >= 1  # at least claude-code
    assert project_count == 0  # the broken one disabled itself
    assert "claude-code" in registered_profile_names()
    assert "broken" in disabled_profile_diagnostics()


def test_load_all_at_startup_idempotent(tmp_path, monkeypatch):
    """Multiple calls don't double-register or break the registry."""
    from harness.cli_profiles import load_all_profiles_at_startup

    monkeypatch.chdir(tmp_path)
    n1 = load_all_profiles_at_startup()
    n2 = load_all_profiles_at_startup()
    assert n1 == n2
    assert "claude-code" in registered_profile_names()
