"""P3-T1: CliProfile dataclass + registry acceptance tests."""
from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from harness.engine.cli_profile import (
    CliProfile,
    CliRunResult,
    CliSpawnConfig,
    disable_profile,
    disabled_profile_diagnostics,
    get_profile,
    register_cli_profile,
    registered_profile_names,
    reset_registry,
)


class _DemoResult(BaseModel):
    summary: str


def _noop_translator(raw, ctx):
    return []


def _identity_extractor(text, result_type):
    return text


def _make_profile(name="test-cli", **overrides):
    defaults = dict(
        name=name,
        prompt_paradigm="minimal",
        cli_path_env="HARNESS_TEST_CLI",
        default_cli_path="test-cli",
        flags=("--foo", "--bar"),
        prompt_channel="stdin",
        mcp_flag_template="--mcp-config {path}",
        env_overlay_prefixes=("TEST_",),
        translator=_noop_translator,
        result_extractor=_identity_extractor,
        default_timeout_s=30.0,
    )
    defaults.update(overrides)
    return CliProfile(**defaults)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test gets a clean registry (registry is process-global).
    After reset, reload builtins so the test sees the same state as
    production startup — without this, downstream tests that depend on
    the "claude-code" profile being registered would fail."""
    reset_registry()
    from harness.cli_profiles import load_builtin_profiles
    load_builtin_profiles()
    yield
    reset_registry()
    load_builtin_profiles()


# ---------------------------------------------------------------------------
# CliProfile field semantics
# ---------------------------------------------------------------------------


def test_profile_required_fields():
    p = _make_profile()
    assert p.name == "test-cli"
    assert p.prompt_paradigm == "minimal"
    assert p.flags == ("--foo", "--bar")
    assert p.default_cli_path == "test-cli"
    assert p.default_timeout_s == 30.0


def test_resolve_cli_path_uses_default_when_env_absent(monkeypatch):
    monkeypatch.delenv("HARNESS_TEST_CLI", raising=False)
    p = _make_profile()
    assert p.resolve_cli_path() == "test-cli"


def test_resolve_cli_path_env_overrides_default(monkeypatch):
    monkeypatch.setenv("HARNESS_TEST_CLI", "/custom/path/test-cli")
    p = _make_profile()
    assert p.resolve_cli_path() == "/custom/path/test-cli"


def test_build_mcp_flag_args_returns_empty_when_template_none():
    p = _make_profile(mcp_flag_template=None)
    assert p.build_mcp_flag_args("/tmp/config.json") == ()


def test_build_mcp_flag_args_returns_empty_when_path_none():
    p = _make_profile()
    assert p.build_mcp_flag_args(None) == ()


def test_build_mcp_flag_args_renders_template():
    p = _make_profile()
    args = p.build_mcp_flag_args("/tmp/config.json")
    assert args == ("--mcp-config", "/tmp/config.json")


# ---------------------------------------------------------------------------
# Registry semantics
# ---------------------------------------------------------------------------


def test_register_and_get():
    p = _make_profile(name="alpha")
    register_cli_profile(p)
    assert get_profile("alpha") is p


def test_register_idempotent_last_write_wins():
    p1 = _make_profile(name="alpha", default_cli_path="v1")
    p2 = _make_profile(name="alpha", default_cli_path="v2")
    register_cli_profile(p1)
    register_cli_profile(p2)
    assert get_profile("alpha").default_cli_path == "v2"


def test_register_rejects_empty_name():
    with pytest.raises(ValueError, match="must be non-empty"):
        register_cli_profile(_make_profile(name=""))


def test_get_unknown_raises_keyerror_with_valid_options():
    register_cli_profile(_make_profile(name="alpha"))
    with pytest.raises(KeyError, match="unknown executor"):
        get_profile("nonexistent")


def test_registered_profile_names_includes_all():
    """Names just registered must be in the set. Other builtins (claude-code)
    may also be present after the fixture reloads them."""
    register_cli_profile(_make_profile(name="alpha"))
    register_cli_profile(_make_profile(name="beta"))
    names = registered_profile_names()
    assert "alpha" in names
    assert "beta" in names


# ---------------------------------------------------------------------------
# Disable semantics
# ---------------------------------------------------------------------------


def test_disable_profile_then_get_raises_valueerror_with_reason():
    register_cli_profile(_make_profile(name="broken"))
    disable_profile("broken", "ImportError: missing dep")
    with pytest.raises(ValueError, match="disabled.*missing dep"):
        get_profile("broken")


def test_disabled_profile_still_in_registered_names():
    """DISABLED names remain in the registry so VALID_EXECUTORS can warn
    operators about the broken profile rather than silently dropping it."""
    register_cli_profile(_make_profile(name="broken"))
    disable_profile("broken", "syntax error")
    assert "broken" in registered_profile_names()


def test_reregistering_clears_disable_flag():
    register_cli_profile(_make_profile(name="broken"))
    disable_profile("broken", "old reason")
    register_cli_profile(_make_profile(name="broken"))  # re-register
    # Now it should be loadable again
    assert get_profile("broken").name == "broken"


def test_disabled_profile_diagnostics_returns_copy():
    register_cli_profile(_make_profile(name="broken"))
    disable_profile("broken", "syntax error")
    diag = disabled_profile_diagnostics()
    diag["injected"] = "should not leak"
    # Second call must NOT see the injected key (defensive copy)
    assert "injected" not in disabled_profile_diagnostics()


# ---------------------------------------------------------------------------
# CliSpawnConfig + CliRunResult dataclasses
# ---------------------------------------------------------------------------


def test_spawn_config_defaults():
    cfg = CliSpawnConfig(
        prompt="hello",
        cli_path="test-cli",
        flags=("--foo",),
        prompt_channel="stdin",
    )
    assert cfg.env_overlay == {}
    assert cfg.mcp_flag_args == ()
    assert cfg.extra_args == ()
    assert cfg.cwd is None


def test_run_result_defaults():
    r = CliRunResult(exit_code=0, stderr="")
    assert r.timed_out is False
