import os
os.environ.setdefault("HARNESS_MODEL", "openai:gpt-4o")
# Skip MCP subprocess startup in lifespan. TestClient-based tests would
# otherwise hang on teardown — MCP stdio subprocesses' anyio task-group
# exit path can block the portal shutdown on this anyio/Python combo.
# Production leaves this unset.
os.environ.setdefault("HARNESS_SKIP_MCP", "1")
