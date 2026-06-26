"""P1-T3: node_factory.py prompt dispatch acceptance tests.

Locks the contract that ``make_node_func`` invokes
``assemble_static_prompt`` with ``executor=agent_def.executor``, so each
backend gets its paradigm-specific base + output format.

Critical regression: prior to P1-T3, ``node_factory`` guarded the assembler
call behind ``if result_type is not None``. That meant free-text agents
(executor=claude-code with no result_type — e.g. ask_user_demo/greeter)
never received ``base_minimal.md`` working norms. P1-T3 removes the guard:
the assembler is now invoked unconditionally, ensuring every agent under
every backend gets the appropriate base layer.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from harness.engine.node_factory import make_node_func


class _StubBuilder:
    """Minimal MacroGraphBuilder stub for exercising make_node_func wiring.

    Only the attributes read before / during assembler invocation are
    populated. The returned node_func is not invoked here, so the rest of
    node_func (state machine, executor.run, etc.) is never reached.
    """
    def __init__(self):
        from unittest.mock import MagicMock
        self.micro_factory = MagicMock()
        self.event_bus = None
        self.max_iterations = 5
        self.workflow_id = "test-wf"
        self._workflow_name = "test-wf"
        self.request_limit = None
        self.envelope = None
        # tool_registry.expand_globs is called inside resolve_agent_config;
        # get_tool_info is called at the top of make_node_func.
        self.tool_registry = MagicMock()
        self.tool_registry.expand_globs.side_effect = lambda names, strict=False: names
        self.micro_factory.tool_registry.get_tool_info.return_value = []


class _StubParsed:
    """Stand-in for ParsedAgent — only the fields read before assembler call."""
    def __init__(self, prompt: str, tools=None, model=None, retries=3):
        self.prompt = prompt
        self.tools = tools or []
        self.model = model
        self.retries = retries


class _StubAgentDef:
    """Stand-in for Agent with configurable executor."""
    def __init__(self, name: str, executor: str = "pydantic-ai",
                 tools=None, model=None, retries=3, after=None,
                 on_pass=None, on_fail=None, result_type=None, eval=None):
        self.name = name
        self.executor = executor
        self.tools = tools or []
        self.model = model
        self.retries = retries
        self.after = after if after is not None else []
        self.on_pass = on_pass
        self.on_fail = on_fail
        self.result_type = result_type
        self.eval = eval
        # has_conditional_edges drives result_type auto-injection in
        # resolve_agent_config; we don't trigger that path here.
        self.has_conditional_edges = bool(on_pass or on_fail)


def _capture_assembler_call(executor: str):
    """Return (patcher, calls_list) — patches assemble_static_prompt to
    record calls without executing."""
    calls: list[dict] = []

    def _spy(agent_md_body, result_type, *, executor="pydantic-ai"):
        calls.append({
            "agent_md_body": agent_md_body,
            "result_type": result_type,
            "executor": executor,
        })
        # Return a recognisable stub so downstream code doesn't crash if it
        # tries to use the prompt.
        return f"<assembled executor={executor}>"

    patcher = patch(
        "harness.engine.node_factory.assemble_static_prompt",
        side_effect=_spy,
    )
    return patcher, calls


def test_node_factory_passes_pydantic_ai_executor_to_assembler():
    """pydantic-ai executor → assembler called with executor='pydantic-ai'."""
    patcher, calls = _capture_assembler_call("pydantic-ai")
    with patcher:
        make_node_func(
            builder=_StubBuilder(),
            agent_def=_StubAgentDef(name="scout", executor="pydantic-ai"),
            parsed=_StubParsed(prompt="# Scout\n\nExplore."),
            dep_map={"scout": []},
            workflow_dir="/tmp",
        )
    assert len(calls) == 1, f"expected exactly 1 assembler call, got {len(calls)}"
    assert calls[0]["executor"] == "pydantic-ai"


def test_node_factory_passes_claude_code_executor_to_assembler():
    """claude-code executor → assembler called with executor='claude-code'
    so the minimal paradigm is selected (base_minimal.md + no final_result)."""
    patcher, calls = _capture_assembler_call("claude-code")
    with patcher:
        make_node_func(
            builder=_StubBuilder(),
            agent_def=_StubAgentDef(name="greeter", executor="claude-code"),
            parsed=_StubParsed(prompt="# Greeter\n\nGreet."),
            dep_map={"greeter": []},
            workflow_dir="/tmp",
        )
    assert len(calls) == 1
    assert calls[0]["executor"] == "claude-code"


def test_node_factory_invokes_assembler_even_when_result_type_is_none():
    """REGRESSION GUARD (P1-T3): free-text agents (result_type=None) MUST
    still go through the assembler so they receive the paradigm's base
    working norms. Prior to P1-T3, the assembler was skipped for these
    agents, leaving claude-code free-text agents without base_minimal.md."""
    patcher, calls = _capture_assembler_call("claude-code")
    with patcher:
        make_node_func(
            builder=_StubBuilder(),
            agent_def=_StubAgentDef(
                name="greeter", executor="claude-code", result_type=None,
            ),
            parsed=_StubParsed(prompt="# Greeter\n\nGreet."),
            dep_map={"greeter": []},
            workflow_dir="/tmp",
        )
    assert len(calls) == 1, (
        "assembler was not called for free-text agent — base layer missing"
    )
    assert calls[0]["result_type"] is None
    assert calls[0]["executor"] == "claude-code"


def test_node_factory_falls_back_to_bare_body_on_assembler_failure(caplog):
    """If the assembler raises a NON-ValueError exception (e.g. broken
    result_type schema), node_func construction must still succeed with
    augmented_prompt = parsed.prompt. WARNING is logged so the operator
    sees that base norms were dropped."""
    with patch(
        "harness.engine.node_factory.assemble_static_prompt",
        side_effect=RuntimeError("schema explosion"),
    ):
        with caplog.at_level("WARNING", logger="harness.engine.node_factory"):
            node_func = make_node_func(
                builder=_StubBuilder(),
                agent_def=_StubAgentDef(name="agent", executor="pydantic-ai"),
                parsed=_StubParsed(prompt="# Agent\n\nDo thing."),
                dep_map={"agent": []},
                workflow_dir="/tmp",
            )
    assert callable(node_func), (
        "make_node_func must return a callable even when assembler raises"
    )
    assert any(
        "falling back to bare agent body" in rec.message for rec in caplog.records
    ), "lenient fallback must log a WARNING so base-norm loss is visible"


def test_node_factory_propagates_value_error_from_assembler():
    """Fail-loud contract: ValueError from the assembler (unknown executor /
    paradigm typo) MUST propagate, not be silently swallowed by the
    schema-fallback except clause. Catching it would mask the config bug
    and run the agent under the wrong paradigm."""
    with patch(
        "harness.engine.node_factory.assemble_static_prompt",
        side_effect=ValueError("unknown paradigm 'claudecode'"),
    ):
        with pytest.raises(ValueError, match="unknown paradigm"):
            make_node_func(
                builder=_StubBuilder(),
                agent_def=_StubAgentDef(name="agent", executor="claudecode"),
                parsed=_StubParsed(prompt="# Agent\n\nDo thing."),
                dep_map={"agent": []},
                workflow_dir="/tmp",
            )
