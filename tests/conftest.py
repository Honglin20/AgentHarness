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

