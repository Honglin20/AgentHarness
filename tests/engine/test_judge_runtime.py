"""Runtime tests for judge node behavior:
- _route_judgment reads from metadata (not outputs)
- Display name rewrite: _judge_X → X in prompts
- Critique injection when judge returns fail
- Passthrough outputs
"""
from harness.engine.macro_graph import _route_judgment
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState
from harness.constants import STATE_METADATA, STATE_OUTPUTS


# --- _route_judgment ---

def test_route_judgment_pass():
    state: HarnessState = {
        STATE_METADATA: {
            "_judge_coder": {"judgment": {"decision": "pass", "reason": "OK"}},
        },
        STATE_OUTPUTS: {},
    }
    assert _route_judgment(state, "_judge_coder") == "pass"


def test_route_judgment_fail():
    state: HarnessState = {
        STATE_METADATA: {
            "_judge_coder": {"judgment": {"decision": "fail", "reason": "Bad"}},
        },
        STATE_OUTPUTS: {},
    }
    assert _route_judgment(state, "_judge_coder") == "fail"


def test_route_judgment_defaults_to_pass_on_missing():
    state: HarnessState = {STATE_METADATA: {}, STATE_OUTPUTS: {}}
    assert _route_judgment(state, "_judge_coder") == "pass"


def test_route_judgment_ignores_outputs():
    """Judge decision is in metadata, not outputs — outputs should not affect routing."""
    state: HarnessState = {
        STATE_METADATA: {
            "_judge_coder": {"judgment": {"decision": "fail", "reason": "Bad"}},
        },
        STATE_OUTPUTS: {"_judge_coder": "pass"},  # misleading string in outputs
    }
    assert _route_judgment(state, "_judge_coder") == "fail"


# --- Display name rewrite ---

def test_display_name_rewrites_judge_prefix():
    assert MicroAgentFactory._display_name("_judge_coder") == "coder"


def test_display_name_leaves_normal_names():
    assert MicroAgentFactory._display_name("analyzer") == "analyzer"


def test_build_node_prompt_rewrites_judge_name():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={},
        upstream_outputs={"_judge_coder": "some output"},
    )
    assert "## Output from coder" in prompt
    assert "## Output from _judge_coder" not in prompt


# --- Critique injection ---

def test_build_node_prompt_with_critique():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "write code"},
        upstream_outputs={},
        critique="Output lacks error handling",
    )
    assert "## Previous judgment" in prompt
    assert "Output lacks error handling" in prompt


def test_build_node_prompt_without_critique():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "write code"},
        upstream_outputs={},
    )
    assert "## Previous judgment" not in prompt


def test_critique_and_display_name_rewrite_together():
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={},
        upstream_outputs={"_judge_coder": "old output"},
        critique="Missing tests",
    )
    assert "## Output from coder" in prompt
    assert "## Previous judgment" in prompt
    assert "Missing tests" in prompt
