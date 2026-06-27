import os
os.environ.setdefault("HARNESS_MODEL", "openai:gpt-4o")
# Skip MCP subprocess startup in lifespan. TestClient-based tests would
# otherwise hang on teardown — MCP stdio subprocesses' anyio task-group
# exit path can block the portal shutdown on this anyio/Python combo.
# Production leaves this unset.
os.environ.setdefault("HARNESS_SKIP_MCP", "1")

# P3-T3+: eagerly load builtin CLI profiles so any test constructing
# ClaudeCodeExecutor (or future CliExecutorBase subclass) gets the
# "claude-code" profile from the registry without each test file
# importing harness.cli_profiles explicitly.
import harness.cli_profiles  # noqa: F401
import pytest


@pytest.fixture(autouse=True)
def _ensure_builtin_profiles_loaded():
    """Reload builtin CLI profiles before each test.

    Profile tests (test_cli_profile_*) call reset_registry() which
    clears everything including builtins. Without this fixture, the next
    test that constructs ClaudeCodeExecutor fails with "claude-code not
    found". Reload right before each test so the registry always has
    builtins available.
    """
    from harness.engine.cli_profile import registered_profile_names
    if "claude-code" not in registered_profile_names():
        from harness.cli_profiles import load_builtin_profiles
        load_builtin_profiles()

