"""Runtime tests for judge node behavior:
- _route_decision reads from outputs (not metadata)
- Display name rewrite: _judge_X → X in prompts
- Critique injection when judge returns fail
- Score chart emission via EvalChartPlugin
"""
import pytest
from unittest.mock import MagicMock
from harness.engine.macro_graph import _route_decision
from harness.engine.schema_utils import ReviewDecision
from harness.engine.micro_agent import MicroAgentFactory
from harness.constants import STATE_METADATA, STATE_OUTPUTS


# --- _route_decision (unified for all nodes including judges) ---

def test_route_decision_pass():
    state = {
        STATE_OUTPUTS: {"_judge_coder": ReviewDecision(decision="pass", reason="OK")},
    }
    assert _route_decision(state, "_judge_coder") == "pass"


def test_route_decision_fail():
    state = {
        STATE_OUTPUTS: {"_judge_coder": ReviewDecision(decision="fail", reason="Bad")},
    }
    assert _route_decision(state, "_judge_coder") == "fail"


def test_route_decision_defaults_to_fail_on_missing_output():
    """When judge node fails (no output), routing should fail — not silently pass."""
    state = {STATE_OUTPUTS: {}}
    assert _route_decision(state, "_judge_coder") == "fail"


def test_route_decision_reads_from_outputs_not_metadata():
    """Judge decision is now in outputs (ReviewDecision), not metadata."""
    state = {
        STATE_OUTPUTS: {"_judge_coder": ReviewDecision(decision="fail", reason="Bad")},
        STATE_METADATA: {"_judge_coder": {"judgment": {"decision": "pass"}}},
    }
    assert _route_decision(state, "_judge_coder") == "fail"


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


# --- Critique extraction from outputs (eval retry loop) ---

def test_critique_extracted_from_outputs_for_eval_retry():
    """When a target agent re-runs after judge fail, critique is extracted
    from outputs (ReviewDecision model), not metadata."""
    outputs = {
        "_judge_researcher": ReviewDecision(decision="fail", reason="Missing error handling"),
    }
    judge_targets = {"_judge_researcher": "researcher"}

    critique = None
    for output_key, output_val in outputs.items():
        if output_key.startswith("_judge_") and hasattr(output_val, "decision"):
            if output_val.decision == "fail":
                target_name = judge_targets.get(output_key)
                if target_name == "researcher":
                    critique = output_val.reason
                    break

    assert critique == "Missing error handling"


def test_critique_not_extracted_when_decision_is_pass():
    """When judge passed, no critique should be extracted for retry."""
    outputs = {
        "_judge_researcher": ReviewDecision(decision="pass", reason="Looks good"),
    }
    judge_targets = {"_judge_researcher": "researcher"}

    critique = None
    for output_key, output_val in outputs.items():
        if output_key.startswith("_judge_") and hasattr(output_val, "decision"):
            if output_val.decision == "fail":
                target_name = judge_targets.get(output_key)
                if target_name == "researcher":
                    critique = output_val.reason
                    break

    assert critique is None


# --- Score chart emission via EvalChartPlugin ---

@pytest.mark.asyncio
async def test_eval_chart_plugin_emits_chart_on_score():
    """EvalChartPlugin should emit chart.render when judge output has a score."""
    from harness.extensions.plugins.eval_chart import EvalChartPlugin
    from harness.extensions.bus import Bus
    from harness.extensions.base import NodeCtx, WorkflowCtx

    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)

    ctx = NodeCtx(
        workflow=WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={}),
        node_id="_judge_coder",
        agent_name="_judge_coder",
        prompt="",
        messages=[],
        upstream_outputs={},
    )
    # Seed prior history (simulates seed from _make_node_func)
    ctx.metadata["_judge_coder"] = {"score_history": [0.6, 0.7]}

    class FakeReview:
        score = 0.85
        decision = "pass"
        reason = "ok"

    sub_id, queue = await bus.subscribe()
    await bus.run_hooks("on_node_end", ctx, FakeReview())

    event = await __import__("asyncio").wait_for(queue.get(), timeout=1.0)
    assert event["type"] == "chart.render"
    assert event["payload"]["chart_type"] == "line"
    assert event["payload"]["data"] == [
        {"iteration": 1, "score": 0.6},
        {"iteration": 2, "score": 0.7},
        {"iteration": 3, "score": 0.85},
    ]
    # Verify score_history was updated in agent metadata
    assert ctx.metadata["_judge_coder"]["score_history"] == [0.6, 0.7, 0.85]


@pytest.mark.asyncio
async def test_eval_chart_plugin_no_chart_without_score():
    """EvalChartPlugin should NOT emit chart when review has no score."""
    from harness.extensions.plugins.eval_chart import EvalChartPlugin
    from harness.extensions.bus import Bus
    from harness.extensions.base import NodeCtx, WorkflowCtx

    plugin = EvalChartPlugin()
    bus = Bus()
    bus.register(plugin)

    ctx = NodeCtx(
        workflow=WorkflowCtx(workflow_id="w1", workflow_name="test", inputs={}),
        node_id="_judge_coder",
        agent_name="_judge_coder",
        prompt="",
        messages=[],
        upstream_outputs={},
    )

    class FakeReview:
        score = None
        decision = "pass"
        reason = "ok"

    await bus.run_hooks("on_node_end", ctx, FakeReview())
    assert ctx._side_effects == []
