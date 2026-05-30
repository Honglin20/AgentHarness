"""Tests for save-time eval materialization (per SPEC.md).

Covers:
  - Workflow.compile() invokes EvalJudge.mutate + persist
  - Workflow.save() rejects uncompiled eval=True
  - Persisted workflow.json has no eval flag
  - Summarize failure aborts compile, leaves no partial state
  - Re-compile on materialized workflow is no-op
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.api import Agent, Workflow
from harness.extensions.eval import EvalCompileError, EvalJudge, EvalNotCompiledError
from harness.extensions.eval import summarizer as summarizer_mod


# ----------------------- helpers -----------------------

def _make_workflow(tmp_path: Path) -> Workflow:
    """Build a workflow with one eval=true target + one downstream + the target MD on disk."""
    wf_dir = tmp_path / "wf"
    (wf_dir / "agents").mkdir(parents=True)
    (wf_dir / "agents" / "x.md").write_text("---\nname: x\n---\nDo a thing.")
    (wf_dir / "agents" / "y.md").write_text("---\nname: y\n---\nDo another thing.")
    return Workflow(
        "wf",
        agents=[Agent("x", after=[], eval=True), Agent("y", after=["x"])],
        workflow_dir=wf_dir,
    )


def _stub_summarizer(monkeypatch, text: str = "Target X must do its job correctly."):
    """Replace LLM summarizer with a deterministic stub."""
    def _fake(target_name, md_content, workflow_dir, llm_call=None):
        return text
    monkeypatch.setattr(summarizer_mod, "summarize_target", _fake)


# ----------------------- mutate-phase regression -----------------------

def test_compile_materializes_judge_node(tmp_path, monkeypatch):
    _stub_summarizer(monkeypatch)
    wf = _make_workflow(tmp_path).use(EvalJudge())
    wf.compile()
    names = [a.name for a in wf.agents]
    assert "_judge_x" in names
    x = next(a for a in wf.agents if a.name == "x")
    assert x.eval is False  # cleared after materialization


def test_compile_persists_judge_md(tmp_path, monkeypatch):
    _stub_summarizer(monkeypatch, text="X must answer correctly.")
    wf = _make_workflow(tmp_path).use(EvalJudge())
    wf.compile()
    md = (wf.workflow_dir / "agents" / "_judge_x.md").read_text()
    assert "_judge_x" in md
    assert "target: x" in md
    assert "X must answer correctly." in md


# ----------------------- save() contract -----------------------

def test_save_rejects_uncompiled_eval(tmp_path):
    wf = _make_workflow(tmp_path)  # NB: no compile() call
    with pytest.raises(EvalNotCompiledError) as exc:
        wf.save()
    assert "x" in str(exc.value)
    assert "compile()" in str(exc.value)


def test_save_after_compile_strips_eval_flag(tmp_path, monkeypatch):
    _stub_summarizer(monkeypatch)
    wf = _make_workflow(tmp_path).use(EvalJudge())
    wf.compile()
    path = wf.save()
    data = json.loads(path.read_text())
    # No agent should still carry eval flag in the persisted JSON
    for a in data["agents"]:
        assert a.get("eval", False) is False
    names = [a["name"] for a in data["agents"]]
    assert "_judge_x" in names
    # The original target y should now depend on the judge, not x
    y_def = next(a for a in data["agents"] if a["name"] == "y")
    assert "_judge_x" in (y_def.get("after") or [])
    assert "x" not in (y_def.get("after") or [])


def test_save_works_without_eval(tmp_path):
    wf_dir = tmp_path / "plain"
    (wf_dir / "agents").mkdir(parents=True)
    (wf_dir / "agents" / "a.md").write_text("---\nname: a\n---\nbody")
    wf = Workflow("plain", agents=[Agent("a")], workflow_dir=wf_dir)
    path = wf.save()
    assert path.exists()


# ----------------------- failure handling -----------------------

def test_compile_aborts_on_summarize_failure(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("LLM unreachable")
    monkeypatch.setattr(summarizer_mod, "summarize_target", _boom)
    wf = _make_workflow(tmp_path).use(EvalJudge())
    with pytest.raises(EvalCompileError) as exc:
        wf.compile()
    assert "summarizer failed" in str(exc.value)
    # No partial MD should have been written
    assert not (wf.workflow_dir / "agents" / "_judge_x.md").exists()


def test_save_blocked_after_failed_compile(tmp_path, monkeypatch):
    """If compile() raises, eval flags stay set, so save() must still refuse."""
    monkeypatch.setattr(summarizer_mod, "summarize_target",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")))
    wf = _make_workflow(tmp_path).use(EvalJudge())
    with pytest.raises(EvalCompileError):
        wf.compile()
    with pytest.raises(EvalNotCompiledError):
        wf.save()


# ----------------------- idempotency -----------------------

def test_compile_idempotent_on_materialized_workflow(tmp_path, monkeypatch):
    _stub_summarizer(monkeypatch)
    wf = _make_workflow(tmp_path).use(EvalJudge())
    wf.compile()
    agents_before = [a.name for a in wf.agents]
    md_mtime = (wf.workflow_dir / "agents" / "_judge_x.md").stat().st_mtime_ns

    # Mutate the MD content to detect any rewrite
    md_path = wf.workflow_dir / "agents" / "_judge_x.md"
    md_path.write_text("SENTINEL — should not be overwritten on re-compile")

    wf.compile()
    agents_after = [a.name for a in wf.agents]
    assert agents_after == agents_before
    assert md_path.read_text() == "SENTINEL — should not be overwritten on re-compile"
    # Mtime check is approximate but should hold on same filesystem
    _ = md_mtime  # documented intent; sentinel check is the real assertion


# ----------------------- structural sanity (still passes from mutate-only tests) -----------------------

def test_downstream_rewired_to_judge(tmp_path, monkeypatch):
    _stub_summarizer(monkeypatch)
    wf = _make_workflow(tmp_path).use(EvalJudge())
    wf.compile()
    y = next(a for a in wf.agents if a.name == "y")
    assert "_judge_x" in y.after
    assert "x" not in y.after


def test_failure_loops_back_to_target(tmp_path, monkeypatch):
    _stub_summarizer(monkeypatch)
    wf = _make_workflow(tmp_path).use(EvalJudge())
    wf.compile()
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_fail == "x"


def test_pass_routes_to_original_downstream(tmp_path, monkeypatch):
    _stub_summarizer(monkeypatch)
    wf = _make_workflow(tmp_path).use(EvalJudge())
    wf.compile()
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_pass == "y"


# ----------------------- new contracts from review -----------------------

def test_eval_target_survives_save_load(tmp_path, monkeypatch):
    """Judge agent's eval_target must round-trip through workflow.json so the
    engine can still route it through _make_judge_node_func after reload."""
    _stub_summarizer(monkeypatch)
    wf = _make_workflow(tmp_path).use(EvalJudge())
    wf.compile()
    wf.save()

    data = json.loads((wf.workflow_dir / "workflow.json").read_text())
    judge_def = next(a for a in data["agents"] if a["name"] == "_judge_x")
    assert judge_def.get("eval_target") == "x"

    wf2 = Workflow.from_dict(data, workflow_dir=wf.workflow_dir)
    judge = next(a for a in wf2.agents if a.name == "_judge_x")
    assert getattr(judge, "eval_target", None) == "x"
    # Legacy attr alias must also be set for in-engine code paths
    assert getattr(judge, "_eval_target", None) == "x"


def test_compile_raises_when_eval_true_unhandled(tmp_path):
    """eval=True without a mutator registered → compile() raises EvalCompileError."""
    wf = _make_workflow(tmp_path)  # NB: no .use(EvalJudge())
    with pytest.raises(EvalCompileError) as exc:
        wf.compile()
    assert "no GraphMutator handled" in str(exc.value)
    assert "x" in str(exc.value)
