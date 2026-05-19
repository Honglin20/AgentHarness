from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
from pydantic_ai import RunContext

from harness.tools.bash import BashToolFactory, DEFAULT_TIMEOUT
from harness.tools.deps import AgentDeps


def _make_ctx(workdir: str = ".", agent_name: str = "test") -> RunContext[AgentDeps]:
    deps = AgentDeps(workdir=workdir, agent_name=agent_name)
    return RunContext(
        deps=deps,
        model=None,
        usage=None,
        prompt=None,
    )


class TestBashToolFactory:
    def test_name(self):
        factory = BashToolFactory()
        assert factory.name == "bash"

    def test_description_keywords(self):
        factory = BashToolFactory()
        for keyword in ("bash", "command", "shell"):
            assert keyword in factory.description.lower()

    def test_create_returns_tool(self):
        factory = BashToolFactory()
        tool = factory.create()
        assert tool is not None

    def test_echo_execution(self):
        factory = BashToolFactory()
        tool = factory.create()
        # Extract the underlying function from the PydanticAI Tool
        bash_fn = tool.function
        ctx = _make_ctx()
        result = bash_fn(ctx, command="echo hello")
        assert "hello" in result

    def test_nonzero_exit_code(self):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = bash_fn(ctx, command="exit 1")
        assert "[exit code: 1]" in result

    def test_stderr_captured(self):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = bash_fn(ctx, command="echo error_msg >&2")
        assert "error_msg" in result
        assert "[stderr]" in result

    def test_timeout(self):
        factory = BashToolFactory(timeout=1)
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = bash_fn(ctx, command="sleep 10")
        assert "timed out" in result
        assert "1s" in result

    def test_default_timeout(self):
        assert DEFAULT_TIMEOUT == 30
        factory = BashToolFactory()
        assert factory.timeout == DEFAULT_TIMEOUT

    def test_custom_timeout(self):
        factory = BashToolFactory(timeout=60)
        assert factory.timeout == 60

    def test_workdir_respected(self, tmp_path):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx(workdir=str(tmp_path))
        result = bash_fn(ctx, command="pwd")
        assert str(tmp_path) in result

    def test_no_output(self):
        factory = BashToolFactory()
        tool = factory.create()
        bash_fn = tool.function
        ctx = _make_ctx()
        result = bash_fn(ctx, command="true")
        assert result == "(no output)"
