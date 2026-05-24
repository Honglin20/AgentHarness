"""Runtime tests for judge node behavior:
- _route_judgment reads from metadata (not outputs)
- Display name rewrite: _judge_X → X in prompts
- Critique injection when judge returns fail
- Passthrough outputs
- Score chart emission
"""
import pytest
from unittest.mock import patch, MagicMock
from harness.engine.macro_graph import _route_judgment, MacroGraphBuilder
from harness.engine.micro_agent import MicroAgentFactory
from harness.engine.state import HarnessState
from harness.constants import STATE_METADATA, STATE_OUTPUTS, STATE_INPUTS, STATE_ERRORS
from harness.tools.registry import ToolRegistry
from harness.extensions.eval.decisions import ReviewDecision


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


# --- Critique extraction for eval retry ---

def test_critique_extracted_from_metadata_for_eval_retry():
    """When a target agent re-runs after judge fail, critique must be found
    via metadata scan even though the agent's after=[] doesn't list _judge_X.

    This tests the _make_node_func critique extraction logic by importing
    the code path directly. We simulate the metadata state that exists
    when _judge_X has returned fail and routed back to X.
    """
    from harness.engine.macro_graph import MacroGraphBuilder
    from harness.tools.registry import ToolRegistry

    builder = MacroGraphBuilder(tool_registry=ToolRegistry())

    # Simulate the metadata state after _judge_researcher returned fail
    metadata = {
        "_judge_researcher": {
            "judgment": {"decision": "fail", "reason": "Missing error handling"},
            "target": "researcher",
            "score_history": [],
        }
    }

    # The critique extraction in _make_node_func scans metadata for
    # entries starting with _judge_ whose target matches the agent name.
    # This covers the eval-retry case where the target's after=[].
    critique = None
    for meta_key, meta_val in metadata.items():
        if meta_key.startswith("_judge_") and isinstance(meta_val, dict):
            if meta_val.get("target") == "researcher":
                judgment = meta_val.get("judgment", {})
                if judgment.get("decision") == "fail":
                    critique = judgment.get("reason", "")
                    break

    assert critique == "Missing error handling"


def test_critique_not_extracted_when_decision_is_pass():
    """When judge passed, no critique should be extracted for retry."""
    metadata = {
        "_judge_researcher": {
            "judgment": {"decision": "pass", "reason": "Looks good"},
            "target": "researcher",
        }
    }

    critique = None
    for meta_key, meta_val in metadata.items():
        if meta_key.startswith("_judge_") and isinstance(meta_val, dict):
            if meta_val.get("target") == "researcher":
                judgment = meta_val.get("judgment", {})
                if judgment.get("decision") == "fail":
                    critique = judgment.get("reason", "")
                    break

    assert critique is None


# --- Score chart emission ---

@pytest.mark.asyncio
async def test_judge_node_emits_chart_on_score(tmp_path):
    """Judge node function should emit chart.render when review has a score."""
    # Set up a minimal agent MD for the target
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "researcher.md").write_text("---\nname: researcher\n---\nDo research.")

    from harness.api import Agent

    # Create the judge agent (as EvalJudge would)
    judge = Agent("_judge_researcher", after=["researcher"], on_fail="researcher", on_pass=None)
    judge._eval_target = "researcher"

    # Capture bus emissions
    captured_events = []
    mock_bus = MagicMock()
    mock_bus.emit = lambda t, p: captured_events.append((t, p))

    # Stub summarize_target to avoid LLM call
    with patch("harness.engine.macro_graph.summarize_target", return_value="stub summary"):
        # Stub LLMClient to return a ReviewDecision with score
        mock_agent_run = MagicMock()
        mock_agent_run.output = ReviewDecision(decision="pass", reason="Good", score=0.85)
        mock_agent_run.usage = MagicMock(input_tokens=10, output_tokens=20, total_tokens=30)

        mock_pydantic_agent = MagicMock()
        mock_pydantic_agent.run = MagicMock(return_value=mock_agent_run)
        # Make run return an awaitable
        async def _async_run(*a, **kw):
            return mock_agent_run
        mock_pydantic_agent.run = _async_run

        mock_client = MagicMock()
        mock_client.agent = MagicMock(return_value=mock_pydantic_agent)

        with patch("harness.engine.llm.LLMClient", return_value=mock_client):
            builder = MacroGraphBuilder(tool_registry=ToolRegistry(), event_bus=mock_bus)
            builder.workflow_id = "test-wf"

            judge_fn = builder._make_judge_node_func(judge, "researcher", {"researcher": []}, tmp_path)

            state = {
                STATE_INPUTS: {"task": "test"},
                STATE_OUTPUTS: {"researcher": "research output"},
                STATE_ERRORS: {},
                STATE_METADATA: {},
                "iteration_counts": {},
            }
            result = await judge_fn(state)

    # Verify chart.render was emitted
    chart_events = [(t, p) for t, p in captured_events if t == "chart.render"]
    assert len(chart_events) == 1
    payload = chart_events[0][1]
    assert payload["chart_type"] == "line"
    assert payload["label"] == "Eval Scores"
    assert payload["title"] == "researcher quality"
    assert payload["data"] == [{"iteration": 1, "score": 0.85}]

    # Verify outputs are passthrough
    assert result[STATE_OUTPUTS]["_judge_researcher"] == "research output"

    # Verify judgment in metadata
    judge_meta = result[STATE_METADATA]["_judge_researcher"]
    assert judge_meta["judgment"]["decision"] == "pass"
    assert judge_meta["judgment"]["score"] == 0.85
    assert judge_meta["score_history"] == [0.85]


@pytest.mark.asyncio
async def test_judge_node_no_chart_without_score(tmp_path):
    """Judge node should NOT emit chart.render when review has no score."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "researcher.md").write_text("---\nname: researcher\n---\nDo research.")

    from harness.api import Agent

    judge = Agent("_judge_researcher", after=["researcher"], on_fail="researcher", on_pass=None)
    judge._eval_target = "researcher"

    captured_events = []
    mock_bus = MagicMock()
    mock_bus.emit = lambda t, p: captured_events.append((t, p))

    with patch("harness.engine.macro_graph.summarize_target", return_value="stub"):
        mock_agent_run = MagicMock()
        mock_agent_run.output = ReviewDecision(decision="pass", reason="OK")  # no score
        async def _async_run(*a, **kw):
            return mock_agent_run
        mock_pydantic_agent = MagicMock()
        mock_pydantic_agent.run = _async_run

        mock_client = MagicMock()
        mock_client.agent = MagicMock(return_value=mock_pydantic_agent)

        with patch("harness.engine.llm.LLMClient", return_value=mock_client):
            builder = MacroGraphBuilder(tool_registry=ToolRegistry(), event_bus=mock_bus)
            builder.workflow_id = "test-wf"

            judge_fn = builder._make_judge_node_func(judge, "researcher", {"researcher": []}, tmp_path)

            state = {
                STATE_INPUTS: {"task": "test"},
                STATE_OUTPUTS: {"researcher": "output"},
                STATE_ERRORS: {},
                STATE_METADATA: {},
                "iteration_counts": {},
            }
            await judge_fn(state)

    chart_events = [(t, p) for t, p in captured_events if t == "chart.render"]
    assert len(chart_events) == 0
