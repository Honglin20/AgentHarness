"""P3-T6: executor_factory profile-registry dispatch tests."""
from __future__ import annotations

import pytest

from harness.engine.executor_factory import make_executor
from harness.engine.claude_code_executor import ClaudeCodeExecutor
from harness.engine.llm_executor import LLMExecutor
from harness.engine.cli_profile import (
    CliProfile, disable_profile, register_cli_profile,
    reset_registry, registered_profile_names,
)


@pytest.fixture(autouse=True)
def _reset_registry_with_builtins():
    reset_registry()
    from harness.cli_profiles import load_builtin_profiles
    load_builtin_profiles()
    yield
    reset_registry()
    load_builtin_profiles()


def _make_dummy_agent_def(executor: str):
    class _A:
        def __init__(self, name, executor):
            self.name = name
            self.executor = executor
    return _A("dummy", executor)


def _make_custom_profile(name="mock-opencode"):
    return CliProfile(
        name=name, prompt_paradigm="minimal",
        cli_path_env="HARNESS_OPENCODE_CLI", default_cli_path="opencode",
        flags=(), prompt_channel="stdin", mcp_flag_template=None,
        env_overlay_prefixes=("X",),
        translator=lambda r, c: [], result_extractor=lambda t, rt: t,
    )


def test_unknown_backend_raises_with_profiles_dir_hint():
    """Unknown executor → ValueError mentioning profile discovery path."""
    agent_def = _make_dummy_agent_def("nonexistent")
    with pytest.raises(ValueError, match="unknown executor.*VALID_EXECUTORS"):
        make_executor(
            agent_def=agent_def, pydantic_agent=None, deps=None,
            workflow_id="w", node_id="n", agent_name="a",
        )


def test_custom_profile_dispatches_to_claude_code_executor_with_profile():
    """A user-registered CLI profile → ClaudeCodeExecutor with that profile."""
    custom = _make_custom_profile(name="mock-opencode")
    register_cli_profile(custom)
    agent_def = _make_dummy_agent_def("mock-opencode")
    ex = make_executor(
        agent_def=agent_def, pydantic_agent=None, deps=None,
        workflow_id="w", node_id="n", agent_name="a",
    )
    assert isinstance(ex, ClaudeCodeExecutor)
    assert ex._profile is custom
    assert ex._profile.name == "mock-opencode"


def test_pydantic_ai_dispatch_unchanged():
    """pydantic-ai → LLMExecutor — registry has no impact on this path."""
    agent_def = _make_dummy_agent_def("pydantic-ai")
    ex = make_executor(
        agent_def=agent_def, pydantic_agent=object(), deps=None,
        workflow_id="w", node_id="n", agent_name="a",
    )
    assert isinstance(ex, LLMExecutor)


def test_claude_code_dispatches_with_default_profile():
    """claude-code → ClaudeCodeExecutor with the builtin claude-code profile."""
    agent_def = _make_dummy_agent_def("claude-code")
    ex = make_executor(
        agent_def=agent_def, pydantic_agent=None, deps=None,
        workflow_id="w", node_id="n", agent_name="a",
    )
    assert isinstance(ex, ClaudeCodeExecutor)
    assert ex._profile.name == "claude-code"


def test_disabled_profile_raises_clear_error():
    """Disabled profile → ValueError pointing at the disable reason."""
    register_cli_profile(_make_custom_profile(name="broken-cli"))
    disable_profile("broken-cli", "ImportError: missing dependency")

    agent_def = _make_dummy_agent_def("broken-cli")
    with pytest.raises(ValueError, match="unavailable.*missing dependency"):
        make_executor(
            agent_def=agent_def, pydantic_agent=None, deps=None,
            workflow_id="w", node_id="n", agent_name="a",
        )
