"""Test that _build_agents_snapshot synthesizes md_content for _judge_X nodes."""
from unittest.mock import MagicMock
from pathlib import Path

from harness.api import Agent
from server.runner import _build_agents_snapshot


def _make_workflow(agents, workflow_dir=None):
    wf = MagicMock()
    wf.agents = agents
    wf.workflow_dir = workflow_dir or Path(__file__).resolve().parent / "compiler" / "fixtures"
    return wf


def test_judge_node_snapshot_contains_evaluator_keyword(tmp_path):
    """_judge_X node gets synthesized md_content with '评测员' keyword."""
    # Create a target agent MD in the workflow's agents/ dir
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "coder.md").write_text("---\nname: coder\n---\n写代码。")

    coder = Agent("coder", after=[], eval=True)
    judge = Agent("_judge_coder", after=["coder"], on_fail="coder", on_pass=None)
    judge._eval_target = "coder"

    workflow = _make_workflow([coder, judge], workflow_dir=tmp_path)

    # Use a stub summarizer so we don't need a real LLM
    import harness.extensions.eval.summarizer as sum_mod
    original = sum_mod.summarize_target

    def _stub_summarize(target_name, md_content, workflow_dir, llm_call=None):
        return "(stub summary)"

    sum_mod.summarize_target = _stub_summarize
    try:
        snapshot = _build_agents_snapshot(workflow)
    finally:
        sum_mod.summarize_target = original

    judge_snap = next(s for s in snapshot if s["name"] == "_judge_coder")
    assert "评测员" in judge_snap["md_content"]
    assert "auto_generated: true" in judge_snap["md_content"]
    assert "target: coder" in judge_snap["md_content"]
    assert "result_type: ReviewDecision" in judge_snap["md_content"]


def test_normal_agent_snapshot_reads_md_from_disk(tmp_path):
    """Non-judge agents still read md_content from disk."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "writer.md").write_text("---\nname: writer\n---\n写作。")

    writer = Agent("writer", after=[])
    workflow = _make_workflow([writer], workflow_dir=tmp_path)

    snapshot = _build_agents_snapshot(workflow)
    assert len(snapshot) == 1
    assert snapshot[0]["md_content"] == "---\nname: writer\n---\n写作。"


def test_passthrough_node_snapshot(tmp_path):
    """Passthrough nodes get a minimal synthesized md_content."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    coder = Agent("coder", after=[], eval=True)
    judge = Agent("_judge_coder", after=["coder"], on_fail="coder", on_pass=None)
    judge._eval_target = "coder"
    pt = Agent("_judge_coder_passthrough", after=["_judge_coder"])

    workflow = _make_workflow([coder, judge, pt], workflow_dir=tmp_path)

    import harness.extensions.eval.summarizer as sum_mod
    original = sum_mod.summarize_target
    sum_mod.summarize_target = lambda *a, **kw: "(stub)"
    try:
        snapshot = _build_agents_snapshot(workflow)
    finally:
        sum_mod.summarize_target = original

    pt_snap = next(s for s in snapshot if s["name"] == "_judge_coder_passthrough")
    assert "auto_generated: true" in pt_snap["md_content"]
    assert "passthrough" in pt_snap["md_content"]
